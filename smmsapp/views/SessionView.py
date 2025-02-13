from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from django.db.models import Q
from ..models import *
from ..serializers.SessionSerializers import ScanSessionSerializer, ScannedDataSerializer, TransactionSerializer
from django.utils import timezone
from ..permissions.CustomPermissions import IsOperator, IsAdminOrParent, IsAdminOnly


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
            student = rfid_card.student
        except RFIDCard.DoesNotExist:
            return Response({'code': 115, 'message': 'Invalid or inactive RFID card'}, status=status.HTTP_404_NOT_FOUND)

        # Validate Canteen Item
        try:
            item = CanteenItem.objects.get(id=item_id)
        except CanteenItem.DoesNotExist:
            return Response({'code': 116, 'message': 'Invalid canteen item'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if student already purchase the item on same session
        if ScannedData.objects.create(session=session, student=student, rfid_card=rfid_card).exists():
            return Response({'code': 119, "message": "Already purchase this item"}, status=status.HTTP_400_BAD_REQUEST)

       # Check if student has exceeded 10 insufficient meals
        if rfid_card.insufficient_meal_count >= 10:
            message = f"Your child {student.first_name} does not get meal today because insuficient balance execeeded 10 times, Please recharge for your child to get a meal. Available Balance is {rfid_card.balance}"
            return Response({'error': 'Meal denied. Student exceeded allowed insufficient meals.'}, status=status.HTTP_403_FORBIDDEN)

        # Deduct balance if sufficient funds
        if rfid_card.balance >= item.price:
            rfid_card.balance -= item.price
            message = f"Your child {student.first_name} purchased {item.name} with price {item.price}. The available balance is {rfid_card.balance}"
        else:
            # Allow the meal but apply penalty (-500)
            rfid_card.balance -= 500  
            rfid_card.insufficient_meal_count += 1
            message = f"Your child {student.first_name} card has purchase {item.name} with price {item.price} and penalt of -500 Tsh. \nWarning: Count left {rfid_card.insufficient_meal_count}/10 before your child's card blocked, Please recharge to avoid further penalts"

        rfid_card.save()

        # Store scanned data
        scanned_data = ScannedData.objects.create(
            session=session,
            student=student,
            rfid_card=rfid_card
        )

        # Log transaction
        transaction = Transaction.objects.create(
            student=student,
            rfid_card=rfid_card,
            item=item,
            amount=item.price if rfid_card.balance >= item.price else -500
        )

        # Notify parent
        parents = ParentStudent.objects.filter(student=student)
        for parent_entry in parents:
            Notification.objects.create(
                recipient=parent_entry.parent,
                transaction=transaction,
                message=message,
                status='pending',
                type='transaction'
            )

        # Return response
        serializer = ScannedDataSerializer(scanned_data)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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


# --- API FOR GET ACTIVE SESSION -----
class ActiveSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        operator = request.user
        # Query the active session (assuming only one can be active at a time)
        active_session = ScanSession.objects.filter(operator = operator,is_active=True, start_at__lte=timezone.now(), end_at__gte=timezone.now()).first()
        
        if active_session:
            serializer = ScanSessionSerializer(active_session)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response({'code': 114, "message": "No active session available."}, status=status.HTTP_404_NOT_FOUND)


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
class SessionListView(APIView, PageNumberPagination):
    permission_classes = [IsAuthenticated]
    page_size = 30

    def post(self, request, *args, **kwargs):
        user = request.user
        search_query = request.data.get("search").strip()

        if user.role == 'operator':
            session = ScanSession.objects.filter(operator=user).order_by('status', 'start_at')
        elif user.role == 'admin':
            session = ScanSession.objects.all().order_by('status', 'start_at')
        else:
            return Response({'code': 403, 'message': 'Only operators can end a session'}, status=status.HTTP_403_FORBIDDEN)
        
        if search_query:
            session = session.filter(
                Q(status__icontains=search_query) | Q(start_at__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(session, request, view=self)
        if result is not None:
            serializer = ScanSessionSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

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
        session_id = self.request.query_params.get('session_id', None)
        search_query = request.data.get("search").strip()

        if session_id:
            session =  ScannedData.objects.filter(session_id=session_id).order_by('-scanned_at')
    
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
    permission_classes = [IsAuthenticated]
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
            transactions = Transaction.objects.filter(student__in=children)
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
    