from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from decimal import Decimal
from django.db import transaction
from django.db.models import F, Sum
from django.db.models import Q
from ..models import *
from ..serializers.sessions import (
    EndSessionRequestSerializer, EndSessionResponseSerializer, ScanRFIDRequestSerializer,
    ScanSessionSerializer, ScannedDataSerializer, SessionListRequestSerializer,
    StartSessionRequestSerializer, TransactionListRequestSerializer, TransactionSerializer,
)
from drf_spectacular.utils import extend_schema
from ..serializers.system import CodeMessageSerializer
from django.utils import timezone
from ..permissions.roles import IsAdminOrOperator, IsOperator, IsAdminParentOrStaff, IsAdminOnly
from ..services.audit import log_action, snapshot
from ..utils import get_admin_scope
from ..services.cards import normalize_uid
from ..throttles import OperatorScanThrottle
from django.conf import settings


# --- API FOR SCAN RFID CARD ----- THIS IS THE MAIN FUNCTIONALITY OF THIS SYSTEM -----
@extend_schema(tags=['sessions'], request=ScanRFIDRequestSerializer,
    responses={201: ScannedDataSerializer, 400: CodeMessageSerializer, 403: CodeMessageSerializer, 404: CodeMessageSerializer})
class ScanRFIDCardView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [OperatorScanThrottle]

    def post(self, request):
        user = request.user

        if user.role != 'operator':
            return Response({'code': 403, 'message': 'Only operators can scan cards'}, status=status.HTTP_403_FORBIDDEN)

        request_serializer = ScanRFIDRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_id = request.data.get('session_id')
        has_card_number = 'card_number' in request.data
        has_card_uid = 'card_uid' in request.data
        if has_card_number == has_card_uid or not request.data.get('card_number' if has_card_number else 'card_uid'):
            return Response({'code': 'CARD_IDENTIFIER_REQUIRED', 'message': 'Provide exactly one of card_number or card_uid.'}, status=status.HTTP_400_BAD_REQUEST)
        is_uid = has_card_uid
        if is_uid:
            from ..services.features import is_enabled
            if not is_enabled('NFC_SCAN'):
                return Response({'code': 'FEATURE_DISABLED', 'feature': 'NFC_SCAN'}, status=status.HTTP_403_FORBIDDEN)
            try:
                card_uid = normalize_uid(request.data.get('card_uid'))
            except ValueError as exc:
                return Response({'code': 'INVALID_CARD_UID', 'message': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            card_number = str(request.data.get('card_number')).strip()
        client_scan_id = request.data.get('client_scan_id')
        if client_scan_id:
            previous = ScannedData.objects.filter(client_scan_id=client_scan_id).first()
            if previous:
                if previous.session.operator_id != user.id:
                    return Response({'code': 'CLIENT_SCAN_ID_CONFLICT', 'message': 'client_scan_id is already used by another operator.'}, status=status.HTTP_409_CONFLICT)
                return Response(ScannedDataSerializer(previous).data, status=status.HTTP_200_OK)
        scan_source = request.data.get('scan_source', 'nfc' if is_uid else 'usb')
        if is_uid and scan_source != 'nfc':
            return Response({'code': 'INVALID_SCAN_SOURCE', 'message': 'UID scans must use scan_source=nfc.'}, status=status.HTTP_400_BAD_REQUEST)
        item_id = request.data.get('item_id')

        # Validate session
        try:
            session = ScanSession.objects.get(id=session_id, status='active')
        except ScanSession.DoesNotExist:
            return Response({'code': 114, 'message': 'Active session not found'}, status=status.HTTP_404_NOT_FOUND)

        # Validate Canteen Item
        try:
            item = CanteenItem.objects.get(id=item_id)
        except CanteenItem.DoesNotExist:
            return Response({'code': 116, 'message': 'Invalid canteen item'}, status=status.HTTP_404_NOT_FOUND)

        # The read-modify-write on rfid_card.balance must be atomic and hold a
        # row lock. Without it, two operators scanning the same card at once (or
        # a double-tap) can both pass the sufficiency check and double-deduct or
        # overdraw the balance, corrupting rfid_card.balance. select_for_update()
        # serializes concurrent scans on the same row so each sees the committed
        # balance; concurrent same-card scans block until the first commit.
        with transaction.atomic():
            # Validate RFID Card, locking the row for the duration of this
            # transaction so the balance read and deduct are race-free.
            try:
                lookup = {'uid_hex': card_uid} if is_uid else {'card_number': card_number}
                rfid_card = RFIDCard.objects.select_for_update().get(**lookup, is_active=True)
                student_or_staff = rfid_card.student_or_staff
            except RFIDCard.DoesNotExist:
                return Response({'code': 115, 'message': 'Invalid or inactive RFID card'}, status=status.HTTP_404_NOT_FOUND)

            item_price = item.price
            if getattr(settings, 'MENU_ENFORCED', False):
                menu_line = DailyMenuItem.objects.select_related('menu').filter(
                    menu__date=timezone.localdate(), menu__meal_type=session.type,
                    item=item, item__is_active=True,
                ).first()
                if menu_line is None:
                    return Response({'code': 'ITEM_NOT_ON_MENU', 'detail': 'This item is not on today\'s menu for this meal.'}, status=status.HTTP_403_FORBIDDEN)
                if menu_line.price_override is not None:
                    item_price = menu_line.price_override

            if BlockedItem.objects.filter(student=student_or_staff, item=item).exists():
                return Response(
                    {'code': 'ITEM_BLOCKED', 'detail': 'This item is blocked by the student\'s parent.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Check if student already purchase the item on same session
            if ScannedData.objects.filter(session=session, student_or_staff=student_or_staff, rfid_card=rfid_card, item=item).exists():
                return Response({'code': 119, "message": "Already purchase this item"}, status=status.HTTP_400_BAD_REQUEST)

            preorder = PreOrder.objects.select_for_update().filter(
                student=student_or_staff, date=timezone.localdate(),
                meal_type=session.type, status='placed',
            ).first()
            preorder_item = None
            if preorder is not None:
                from ..services.preorders import fulfil_preorder_item
                from ..models import PreOrderItem
                preorder_item = PreOrderItem.objects.filter(preorder=preorder, item=item, fulfilled_quantity__lt=F('quantity')).first()
                if preorder_item is not None:
                    from ..services.features import is_enabled
                    from ..services.stock import consume_stock
                    stock_movement = None
                    if is_enabled('STOCK'):
                        consumed = consume_stock(item, actor=user, enforce=getattr(settings, 'STOCK_ENFORCED', False))
                        if consumed is False:
                            return Response(
                                {'code': 'OUT_OF_STOCK', 'detail': 'This item is currently out of stock.'},
                                status=status.HTTP_409_CONFLICT,
                            )
                        if isinstance(consumed, StockMovement):
                            stock_movement = consumed
                    fulfilled = fulfil_preorder_item(preorder, item, actor=user)
                    if fulfilled is not None:
                        transaction_record = Transaction.objects.create(
                            student_or_staff=student_or_staff, rfid_card=rfid_card, item=item,
                            amount=fulfilled.unit_price, charged_amount=Decimal('0.00'),
                            transaction_status='successful', session=session, scan_source=scan_source,
                            preorder_item=fulfilled,
                        )
                        from ..models import TransactionPayment
                        from ..models import JournalEntry
                        preorder_entry = JournalEntry.objects.filter(
                            idempotency_key=f'preorder-fulfil:{preorder.id}:{fulfilled.item_id}',
                        ).first()
                        if preorder_entry:
                            TransactionPayment.objects.create(
                                transaction=transaction_record, source='preorder',
                                amount=fulfilled.unit_price, journal_entry=preorder_entry,
                            )
                        if stock_movement:
                            stock_movement.source_transaction = transaction_record
                            stock_movement.save(update_fields=['source_transaction'])
                        scanned_data = ScannedData.objects.create(
                            session=session, student_or_staff=student_or_staff, rfid_card=rfid_card,
                            item=item, scan_source=scan_source, client_scan_id=client_scan_id,
                        )
                        scanned_data._preorder_fulfilled = True
                        scanned_data._payment_breakdown = [{'source': 'preorder', 'amount': str(fulfilled.unit_price)}]
                        from ..services.webhooks import dispatch_webhook_event
                        transaction.on_commit(lambda: dispatch_webhook_event(
                            student_or_staff.school_id, 'meal.purchased',
                            {'transaction_id': str(transaction_record.id), 'card_id': str(rfid_card.id),
                             'item_id': item.id, 'amount': str(fulfilled.unit_price)},
                        ))
                        preorder.refresh_from_db(fields=['status'])
                        if preorder.status == 'fulfilled':
                            from ..services.preorders import notify_preorder
                            notify_preorder(preorder, 'fulfilled', f'The pre-order for {preorder.date} was fully served.')
                        return Response(ScannedDataSerializer(scanned_data).data, status=status.HTTP_201_CREATED)

            spending_rule = SpendingRule.objects.filter(student=student_or_staff).first()
            if spending_rule and spending_rule.daily_limit is not None:
                spent_today = Transaction.objects.filter(
                    student_or_staff=student_or_staff,
                    transaction_date__date=timezone.localdate(),
                    transaction_status__in=['successful', 'penalty'],
                    is_voided=False,
                ).aggregate(total=Sum('charged_amount'))['total'] or Decimal('0.00')
                if spent_today + item_price > spending_rule.daily_limit:
                    return Response(
                        {'code': 'DAILY_LIMIT', 'detail': 'This purchase would exceed the student\'s daily spending limit.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )

            # Check if student has exceeded 10 insufficient meals
            if rfid_card.insufficient_meal_count >= settings.STRIKE_LIMIT:
                if student_or_staff.role == 'student':
                    title = f"{student_or_staff.first_name}'s Card Blocked"
                    message = f"Your child {student_or_staff.first_name} does not get meal today because insufficient balance exceeded {settings.STRIKE_LIMIT} times. Please recharge. Available balance is {rfid_card.balance}"
                else: 
                    title = f"Your Card Blocked"
                    message = f"Your card is blocked after {settings.STRIKE_LIMIT} insufficient-balance penalties. Please recharge your account to unblock it."
                return Response({'code': 118, 'message': 'Meal denied. Customer exceeded allowed insufficient meals.'}, status=status.HTTP_403_FORBIDDEN)

            from ..services.features import is_enabled
            from ..services.stock import consume_stock
            stock_movement = None
            if is_enabled('STOCK'):
                consumed = consume_stock(item, actor=user, enforce=getattr(settings, 'STOCK_ENFORCED', False))
                if consumed is False:
                    return Response(
                        {'code': 'OUT_OF_STOCK', 'detail': 'This item is currently out of stock.'},
                        status=status.HTTP_409_CONFLICT,
                    )
                if isinstance(consumed, StockMovement):
                    stock_movement = consumed

            # Waterfall: pre-order (handled above), sponsor allocations, then wallet.
            sponsor_shares = []
            has_sponsor_allocation = False
            from ..services.features import is_enabled
            if is_enabled('SPONSORSHIP'):
                from ..services.sponsorship import allocate_sponsor_shares, has_eligible_allocation
                has_sponsor_allocation = has_eligible_allocation(student_or_staff, session.type, timezone.localdate())
                sponsor_shares = allocate_sponsor_shares(
                    student_or_staff, session.type, timezone.localdate(), item_price,
                )
            sponsor_total = sum((share for _, share in sponsor_shares), Decimal('0.00'))
            wallet_meal_amount = max(Decimal('0.00'), item_price - sponsor_total)
            if has_sponsor_allocation and wallet_meal_amount > 0 and not getattr(settings, 'SPONSOR_FALLBACK_TO_WALLET', True):
                transaction.set_rollback(True)
                return Response(
                    {'code': 'SPONSOR_FUNDS_EXHAUSTED', 'detail': 'Available sponsor funds cannot cover this meal.'},
                    status=status.HTTP_409_CONFLICT,
                )

            # Deduct only the remaining wallet portion; penalty applies only to it.
            old_balance = rfid_card.balance  # capture before change
            penalty_amount = Decimal('0.00')
            if wallet_meal_amount == 0 or rfid_card.balance >= wallet_meal_amount:
                rfid_card.balance -= wallet_meal_amount
                amount = item_price
                trans_status = 'successful'
                title = f"Transaction Report"
                if student_or_staff.role == 'student':
                    message = f"Your child {student_or_staff.first_name} purchased {item.name} with price {item_price}. The available balance is {rfid_card.balance}"
                else:
                    message = f"You purchased {item.name} with price {item_price}. The available balance is {rfid_card.balance}. If is not you contact with our support imidietly"
            else:
                # Allow the meal but apply penalty (-500). Clamp to the balance
                # floor (-500.00) so the invariant enforced by the model remains
                # satisfied even when the balance was already negative.
                penalty_amount = Decimal(str(settings.PENALTY_FEE))
                rfid_card.balance = max(
                    rfid_card.balance - (wallet_meal_amount + penalty_amount),
                    Decimal(str(settings.RFID_BALANCE_FLOOR)),
                )
                rfid_card.insufficient_meal_count += 1
                amount = item_price + penalty_amount
                trans_status = 'penalty'
                title = f"WARNING: Transaction Penalty"
                if student_or_staff.role == 'student':
                    message = f"Your child {student_or_staff.first_name} has purchased {item.name} for {item_price} with a penalty of {settings.PENALTY_FEE}. Available balance is {rfid_card.balance}. \nWarning: {rfid_card.insufficient_meal_count}/{settings.STRIKE_LIMIT} penalties before the card is blocked. Please recharge."
                else:
                    message = f"Your purchase {item.name} costs {item_price} with a penalty of {settings.PENALTY_FEE}. Available balance is {rfid_card.balance}. \nWarning: {rfid_card.insufficient_meal_count}/{settings.STRIKE_LIMIT} penalties before your card is blocked. Please recharge."


            charged_amount = old_balance - rfid_card.balance
            rfid_card.save()

            # Log transaction
            transaction_record = Transaction.objects.create(
                student_or_staff=student_or_staff,
                rfid_card=rfid_card,
                item=item,
                amount=amount,
                charged_amount=charged_amount,
                transaction_status=trans_status,
                session=session,
                scan_source=scan_source,
            )
            if stock_movement:
                stock_movement.source_transaction = transaction_record
                stock_movement.save(update_fields=['source_transaction'])

            # Write ledger entry for the balance change
            from ..models import LedgerEntry
            if trans_status == 'successful':
                LedgerEntry.objects.create(
                    rfid_card=rfid_card,
                    event_type='purchase',
                    amount=-charged_amount,  # actual wallet delta
                    balance_before=old_balance,
                    balance_after=rfid_card.balance,
                    ref_transaction=transaction_record,
                )
            else:  # penalty
                LedgerEntry.objects.create(
                    rfid_card=rfid_card,
                    event_type='penalty',
                    amount=-charged_amount,
                    balance_before=old_balance,  # captured before penalty was applied
                    balance_after=rfid_card.balance,
                    ref_transaction=transaction_record,
                )

            from ..services.ledger import post_fund_spend, post_wallet_meal
            from ..models import TransactionPayment
            for fund, share in sponsor_shares:
                fund_entry = post_fund_spend(transaction_record, fund, share, actor=user)
                TransactionPayment.objects.create(
                    transaction=transaction_record, source='fund', fund=fund,
                    amount=share, journal_entry=fund_entry,
                )
            wallet_entry = post_wallet_meal(
                transaction_record, wallet_meal_amount, penalty_amount, actor=user,
            )
            if wallet_meal_amount > 0 and wallet_entry:
                TransactionPayment.objects.create(
                    transaction=transaction_record, source='wallet',
                    amount=wallet_meal_amount, journal_entry=wallet_entry,
                )

            try:
                log_action('create', obj=transaction_record, after=snapshot(transaction_record))
            except Exception:
                pass
            # Store scanned data
            scanned_data = ScannedData.objects.create(
                session=session,
                student_or_staff=student_or_staff,
                rfid_card=rfid_card,
                item=item,
                scan_source=scan_source,
                client_scan_id=client_scan_id,
            )
            if trans_status == 'successful':
                from ..services.webhooks import dispatch_webhook_event
                transaction.on_commit(lambda: dispatch_webhook_event(
                    student_or_staff.school_id, 'meal.purchased',
                    {'transaction_id': str(transaction_record.id), 'card_id': str(rfid_card.id),
                     'item_id': item.id, 'amount': str(charged_amount)},
                ))

            # Notify parent (email/push via Notification + SMS for feature phones)
            parents = ParentStudent.objects.filter(student=student_or_staff)
            for parent_entry in parents:
                notif = Notification.objects.create(
                    title=title,
                    recipient=parent_entry.parent,
                    transaction=transaction_record,
                    message=message,
                    status='pending',
                    type='transaction'
                )
                if trans_status == 'penalty':
                    try:
                        from ..services.sms import send_critical_sms
                        sms_body = f"SMMS penalty: {student_or_staff.first_name} charged {charged_amount} (incl. {settings.PENALTY_FEE} penalty). Balance {rfid_card.balance}. Top up to avoid blocking."
                        send_critical_sms(parent_entry.parent, sms_body, notification=notif)
                    except Exception:
                        pass

            # Raise a low-balance reminder if the balance dropped below the parent threshold
            from ..services.alerts import maybe_alert_low_balance
            maybe_alert_low_balance(rfid_card, student_or_staff)

            # Return response
            serializer = ScannedDataSerializer(scanned_data)
            serializer_data = dict(serializer.data)
            serializer_data['payment_breakdown'] = [
                {'source': 'fund', 'fund_id': fund.pk, 'fund_name': fund.name, 'amount': str(share)}
                for fund, share in sponsor_shares
            ]
            if wallet_meal_amount > 0:
                serializer_data['payment_breakdown'].append({'source': 'wallet', 'amount': str(wallet_meal_amount)})
            serializer_data['preorder_fulfilled'] = False
            return Response(serializer_data, status=status.HTTP_201_CREATED)


# --- API FOR GET ACTIVE SESSION -----
@extend_schema(tags=['sessions'], responses={200: ScanSessionSerializer, 404: CodeMessageSerializer})
class ActiveSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        operator = request.user
        # Query the active session (assuming only one can be active at a time)
        active_session = ScanSession.objects.filter(operator = operator,status="active").first()
        
        if active_session:
            serializer = ScanSessionSerializer(active_session)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response({'code': 114, "message": "No active session available."}, status=status.HTTP_404_NOT_FOUND)
        

# ---- API FOR START SESSION ----
@extend_schema(tags=['sessions'], request=StartSessionRequestSerializer,
    responses={201: ScanSessionSerializer, 400: CodeMessageSerializer, 403: CodeMessageSerializer})
class StartScanSessionView(APIView):
    permission_classes = [IsOperator]

    def post(self, request):
        try: 
            user = request.user
            if user.role != 'operator':
                return Response({'code': 403, 'message': 'Only operators can start a session'}, status=status.HTTP_403_FORBIDDEN)

            session_type = request.data.get('type')

            # Check if an active session already exists for this operator
            if ScanSession.objects.filter(operator=user, status='active').exists():
                return Response({'code': 113, 'message': 'You already have an active session'}, status=status.HTTP_400_BAD_REQUEST)

            session = ScanSession.objects.create(operator=user, type=session_type)
            serializer = ScanSessionSerializer(session)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"},status=status.HTTP_400_BAD_REQUEST)


# --- API FOR END SESSION -----
@extend_schema(tags=['sessions'], request=EndSessionRequestSerializer,
    responses={200: EndSessionResponseSerializer, 400: CodeMessageSerializer, 403: CodeMessageSerializer, 404: CodeMessageSerializer})
class EndScanSessionView(APIView):
    permission_classes = [IsOperator]

    def post(self, request, *args, **kwargs):
        try:
            user = request.user
            session_id = request.data.get('session_id')

            if user.role != 'operator':
                return Response({'code': 403, 'message': 'Only operators can end a session'}, status=status.HTTP_403_FORBIDDEN)
            
            try:
                session = ScanSession.objects.get(id=session_id, operator=user, status='active')
            except ScanSession.DoesNotExist:
                return Response({'code': 114, 'message': 'Active session not found'}, status=status.HTTP_404_NOT_FOUND)

            # ---- RECONCILIATION: compute scanned value, ask operator for expected cash ----
            from decimal import Decimal
            from ..services.session_summary import session_summary

            totals = session_summary(session)
            scanned_total = totals['scanned_value']

            from ..services.preorders import release_preorder
            open_orders = PreOrder.objects.filter(date=timezone.localdate(), meal_type=session.type, status='placed')
            for order in open_orders:
                release_preorder(order, status_value='no_show', actor=user, fee=settings.PREORDER_NOSHOW_FEE)

            # Read expected cash from request (operator inputs actual till amount)
            expected_cash = Decimal(request.data.get('expected_cash', '0.00') or '0.00')

            variance = expected_cash - scanned_total

            from ..models import Reconciliation
            reconciliation, created = Reconciliation.objects.get_or_create(
                session=session,
                defaults={
                    'scanned_value': scanned_total,
                    'expected_cash': expected_cash,
                    'variance': variance,
                    'status': 'matched' if variance == 0 else 'variance',
                    'reason': request.data.get('reason', '') if variance != 0 else '',
                },
            )
            if not created:
                # Update existing reconciliation if session is re-ended
                reconciliation.scanned_value = scanned_total
                reconciliation.expected_cash = expected_cash
                reconciliation.variance = variance
                reconciliation.status = 'matched' if variance == 0 else 'variance'
                reconciliation.reason = request.data.get('reason', '') if variance != 0 else ''
                reconciliation.save()

            session.status = 'completed'
            session.end_at = timezone.now()
            session.save()

            totals = session_summary(session)
            return Response({
                'scanned_value': f"{totals['scanned_value']:.2f}",
                'penalty_value': f"{totals['penalty_value']:.2f}",
                'expected_cash': f"{totals['expected_cash']:.2f}",
                'variance': f"{totals['variance']:.2f}",
                'status': totals['status'],
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"},status=status.HTTP_400_BAD_REQUEST)


# ----- API FOR GET SESSION LIST -----
@extend_schema(tags=['sessions'], request=SessionListRequestSerializer,
    responses={200: ScanSessionSerializer(many=True), 403: CodeMessageSerializer})
class SessionListView(APIView):
    permission_classes = [IsAdminOrOperator]

    def post(self, request, *args, **kwargs):
        user = request.user

        if user.role == 'operator':
            session = ScanSession.objects.filter(operator=user).order_by('status', '-start_at')[:10]
        elif user.role == 'admin':
            session = ScanSession.objects.all().order_by('status', '-start_at')[:20]
        else:
            return Response({'code': 403, 'message': 'Only operators can end a session'}, status=status.HTTP_403_FORBIDDEN)

        # If fail return all data/fields
        serializer = ScanSessionSerializer(session, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

# ---- API FOR FETCH SCANNED RFID CARD DATA ----
class ScannedDataListView(APIView, PageNumberPagination):
    permission_classes = [IsAuthenticated]
    serializer_class = ScannedDataSerializer
    page_size = 50
    
    def post(self, request, *args, **kwargs):
        user = request.user
        session_id = request.data.get('session_id')
        search_query = (request.data.get("search") or "").strip()

        if not session_id:
            return Response({'code': 120, "message": "Session id is required"}, status=status.HTTP_400_BAD_REQUEST)

        session = ScannedData.objects.filter(session=session_id).order_by('-scanned_at')

        if not session:
            return Response({"code": 121, "message": "No scanned data found for this session"}, status=status.HTTP_404_NOT_FOUND)

        if search_query:
            session = session.filter(
                Q(rfid_card__card_number__icontains=search_query) |
                Q(student_or_staff__username__icontains=search_query) |
                Q(student_or_staff__first_name__icontains=search_query) |
                Q(student_or_staff__last_name__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(session, request, view=self)
        if result is not None:
            serializer = ScannedDataSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = ScannedDataSerializer(session, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---- API FOR FETCH TRANSACTIONSERIALIZER -----
@extend_schema(tags=['sessions'], request=TransactionListRequestSerializer,
    responses={200: TransactionSerializer(many=True), 403: CodeMessageSerializer})
class TransactionListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminParentOrStaff]
    page_size = 50

    def post(self, request, *args, **kwargs):
        user = request.user
        search_query = (request.data.get("search") or "").strip()

        # Admins can see all transactions (school-scoped when school-admin)
        if user.role == 'admin':
            transactions = Transaction.objects.prefetch_related('payment_parts__fund').all().order_by('-transaction_date')
            school = get_admin_scope(user)
            if school is not None:
                transactions = transactions.filter(student_or_staff__school=school)
        # Parents can only see transactions for their children
        elif user.role == 'parent':
             # Get all ParentStudent relationships for the current user (parent)
            parent_students = ParentStudent.objects.filter(parent=user)
            # Extract the student users from the ParentStudent relationships
            children = [parent_student.student for parent_student in parent_students]
            # Filter transactions for those students
            transactions = Transaction.objects.filter(student_or_staff__in=children).prefetch_related('payment_parts__fund').order_by('-transaction_date')
        # Parents can only see transactions for their children
        elif user.role == 'staff':
            transactions = Transaction.objects.filter(student_or_staff=user).prefetch_related('payment_parts__fund').order_by('-transaction_date')
        else:
            return Response({'code': 403, 'message': 'Unauthorized access'}, status=status.HTTP_403_FORBIDDEN)
        
        if search_query:
            transactions = transactions.filter(
                Q(transaction_status__icontains=search_query) | Q(transaction_date__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(transactions, request, view=self)
        if result is not None:
            serializer = TransactionSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
