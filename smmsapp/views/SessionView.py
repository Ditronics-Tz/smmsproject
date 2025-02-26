from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from django.db.models import Q
from ..models import *
from ..serializers.SessionSerializers import ScanSessionSerializer, ScannedDataSerializer, TransactionSerializer
from django.utils import timezone
from ..permissions.CustomPermissions import IsAdminOrOperator, IsOperator, IsAdminOrParent, IsAdminOnly


# --- API FOR SCAN RFID CARD ----- THIS IS THE MAIN FUNCTIONALITY OF THIS SYSTEM -----
class ScanRFIDCardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if user.role != 'operator':
            return Response({'code': 403, 'message': 'Only operators can scan cards'}, status=status.HTTP_403_FORBIDDEN)

        session_id = request.data.get('session_id')
        card_number = request.data.get('card_number')
        item_id = request.data.get('item_id')

        # Validate session
        try:
            session = ScanSession.objects.get(id=session_id, status='active')
        except ScanSession.DoesNotExist:
            return Response({'code': 114, 'message': 'Active session not found'}, status=status.HTTP_404_NOT_FOUND)

        # Validate RFID Card
        try:
            rfid_card = RFIDCard.objects.get(card_number=card_number, is_active=True)
            student_or_staff = rfid_card.student_or_staff
        except RFIDCard.DoesNotExist:
            return Response({'code': 115, 'message': 'Invalid or inactive RFID card'}, status=status.HTTP_404_NOT_FOUND)

        # Validate Canteen Item
        try:
            item = CanteenItem.objects.get(id=item_id)
        except CanteenItem.DoesNotExist:
            return Response({'code': 116, 'message': 'Invalid canteen item'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if student already purchase the item on same session
        if ScannedData.objects.filter(session=session, student_or_staff=student_or_staff, rfid_card=rfid_card, item=item).exists():
            return Response({'code': 119, "message": "Already purchase this item"}, status=status.HTTP_400_BAD_REQUEST)

       # Check if student has exceeded 10 insufficient meals
        if rfid_card.insufficient_meal_count >= 10:
            if student_or_staff.role == 'student':
                title = f"{student_or_staff.first_name}'s Card Blocked"
                message = f"Your child {student_or_staff.first_name} does not get meal today because insuficient balance execeeded 10 times, Please recharge for your child to get a meal. Available Balance is {rfid_card.balance}"
            else: 
                title: f"Your Card Blocked"
                message = f"Your card is blocked as you get penalt 10 times after insuficient balance in your account. Please recharge your account to unblock"
            return Response({'code': 118, 'message': 'Meal denied. Customer exceeded allowed insufficient meals.'}, status=status.HTTP_403_FORBIDDEN)

        # Deduct balance if sufficient funds
        if rfid_card.balance >= item.price:
            rfid_card.balance -= item.price
            trans_status = 'successful'
            title = f"Transaction Report"
            if student_or_staff.role == 'student':
                message = f"Your child {student_or_staff.first_name} purchased {item.name} with price {item.price}. The available balance is {rfid_card.balance}"
            else:
                message = f"You purchased {item.name} with price {item.price}. The available balance is {rfid_card.balance}. If is not you contact with our support imidietly"
        else:
            # Allow the meal but apply penalty (-500)
            rfid_card.balance -= (item.price + 500)  
            rfid_card.insufficient_meal_count += 1
            trans_status = 'penalt'
            title = f"WARNING: Transaction Penalt"
            if student_or_staff.role == 'stundent':
                message = f"Your child {student_or_staff.first_name} has purchase {item.name} with price {item.price} and penalt of -500 Tsh.Available Balance is {rfid_card.balance}. \nWarning: Count left {rfid_card.insufficient_meal_count}/10 before your child's card blocked, Please recharge to avoid further penalts"
            else:
                message = f"Your purchase {item.name} with price {item.price} and penalt of -500 Tsh.Available Balance is {rfid_card.balance}. \nWarning: Count left {rfid_card.insufficient_meal_count}/10 before your card blocked, Please recharge to avoid further penalts"


        rfid_card.save()

        # Store scanned data
        scanned_data = ScannedData.objects.create(
            session=session,
            student_or_staff=student_or_staff,
            rfid_card=rfid_card,
            item=item
        )

        # Log transaction
        transaction = Transaction.objects.create(
            student_or_staff=student_or_staff,
            rfid_card=rfid_card,
            item=item,
            amount=item.price if rfid_card.balance >= item.price else (item.price + 500),
            transaction_status = trans_status
        )

        # Notify parent
        parents = ParentStudent.objects.filter(student=student_or_staff)
        for parent_entry in parents:
            Notification.objects.create(
                title=title,
                recipient=parent_entry.parent,
                transaction=transaction,
                message=message,
                status='pending',
                type='transaction'
            )

        # Return response
        serializer = ScannedDataSerializer(scanned_data)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# --- API FOR GET ACTIVE SESSION -----
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

            session.status = 'completed'
            session.end_at = timezone.now()
            session.save()

            serializer = ScanSessionSerializer(session)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"},status=status.HTTP_400_BAD_REQUEST)


# ----- API FOR GET SESSION LIST -----
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
        search_query = request.data.get("search").strip()

        session =  ScannedData.objects.filter(session=session_id).order_by('-scanned_at')

        if not session_id:
            return Response({'code': 120, "message": "Session id is required"}, status=status.HTTP_400_BAD_REQUEST)

        if not session:
            return Response({"code": 121, "message": "No scanned data found for this session"}, status=status.HTTP_404_NOT_FOUND)
    
        if search_query:
            session = session.filter(
                Q(status__icontains=search_query) | Q(start_at__icontains=search_query)
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
class TransactionListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminOrParent]
    page_size = 50

    def post(self, request, *args, **kwargs):
        user = request.user
        search_query = request.data.get("search").strip()

        # Admins can see all transactions
        if user.role == 'admin':
            transactions = Transaction.objects.all().order_by('-transaction_date')
        # Parents can only see transactions for their children
        elif user.role == 'parent':
             # Get all ParentStudent relationships for the current user (parent)
            parent_students = ParentStudent.objects.filter(parent=user)
            # Extract the student users from the ParentStudent relationships
            children = [parent_student.student for parent_student in parent_students]
            # Filter transactions for those students
            transactions = Transaction.objects.filter(student_or_staff__in=children).order_by('-transaction_date')
        # Parents can only see transactions for their children
        elif user.role == 'staff':
            transactions = Transaction.objects.filter(student_or_staff=user).order_by('-transaction_date')
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
    