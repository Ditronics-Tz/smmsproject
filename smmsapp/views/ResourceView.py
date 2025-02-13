from django.contrib.auth import authenticate
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, DjangoModelPermissionsOrAnonReadOnly, IsAuthenticated, IsAdminUser
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ..serializers import *
from ..models import *
from ..permissions.CustomPermissions import IsAdminOrParent, IsAdminOnly

# ----- API FOR GET SCHOOL -----
class SchoolListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminUser]
    page_size = 50

    def post(self, request, *args, **kwargs):
        search_query = request.data.get("search").strip()
        school = School.objects.all().order_by('name')

        if search_query:
            school = school.filter(
                Q(name__icontains=search_query) | Q(location__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(school, request, view=self)
        if result is not None:
            serializer =SchoolSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = SchoolSerializer(school, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API TO ADD SCHOOL ----
class CreateSchoolView(generics.CreateAPIView):
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    permission_classes = [IsAuthenticated]


# ---- API FOR DELETE SCHOOL -----
class DeleteSchoolView(APIView):
    permission_classes = [IsAdminUser]
    def post(self, request, *args, **kwargs):
        try:
            # Get school ID from request body
            school_id = request.data.get("school_id")
            if not school_id:
                return Response({"code" : 104, "message": "School ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if school exists
            try:
                school = School.objects.get(id=school_id)
            except School.DoesNotExist:
                return Response({"code": 404, "message": "School not found"}, status=status.HTTP_404_NOT_FOUND)

            # Delete the card
            school.delete()
            return Response({"message": "School deleted successfully.", "school_id": school_id}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})


# ----- API FOR GET USER LIST -----
class UserListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminOnly]  #Requires authentication
    page_size = 50 

    def post(self, request, *args, **kwargs):
        search_query = request.data.get("search").strip()
        role = request.data.get("role")
        users = CustomUser.objects.filter(role=role, is_active=True).exclude(id=request.user.id).order_by("first_name")  # Filter by role

        if search_query:
            users = users.filter(
                Q(first_name__icontains=search_query) | Q(last_name__icontains=search_query) | Q(middle_name__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(users, request, view=self)
        if result is not None:
            serializer =UserSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR GET USER LIST -----
class InactiveUserListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminOnly]  #Requires authentication
    page_size = 50 

    def post(self, request, *args, **kwargs):
        search_query = request.data.get("search").strip()
        users = CustomUser.objects.filter(is_active=False).exclude(id=request.user.id).order_by("first_name")  # Filter by role

        if search_query:
            users = users.filter(
                Q(first_name__icontains=search_query) | Q(last_name__icontains=search_query) | Q(middle_name__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(users, request, view=self)
        if result is not None:
            serializer =UserSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
  

# ----- API FOR FETCH STUDENT DATA -----
class StudentDetailView(generics.RetrieveAPIView):
    queryset = CustomUser.objects.filter(role='student')
    serializer_class = FullStudentSerializer,
    permission_class = [IsAdminOrParent]

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role not in ['admin','parent']:
            return Response({"code": 403,  "message": "Access denied. Only admins and parents can view student details"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        student_id = request.data.get("student_id")

        if not student_id:
            return Response({
                "code": 104,
                "message": "Student id required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        student = get_object_or_404(CustomUser, id=student_id, role = 'student')
        serializer = FullStudentSerializer(student)

        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR FETCH PARENT DATA -----
class ParentDetailView(generics.RetrieveAPIView):
    queryset = CustomUser.objects.filter(role='parent')
    serializer_class = FullParentSerializer,
    permission_class = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response(
                {
                    "code": 403,
                    "message": "Access denied. Only admins can view parents details"
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        parent_id = request.data.get("parent_id")

        if not parent_id:
            return Response({
                "code": 104,
                "message": "Parent id required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        parent = get_object_or_404(CustomUser, id=parent_id, role = 'parent')
        serializer = FullParentSerializer(parent)

        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR FETCH OPERATORS DATA -----
class OperatorDetailView(generics.RetrieveAPIView):
    queryset = CustomUser.objects.filter(role='operator')
    serializer_class = FullOperatorSerializer,
    permission_class = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response(
                {
                    "code": 403,
                    "message": "Access denied. Only admins can view operator details"
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        operator_id = request.data.get("operator_id")

        if not operator_id:
            return Response({
                "code": 104,
                "message": "Parent id required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        operator = get_object_or_404(CustomUser, id=operator_id, role = 'operator')
        serializer = FullOperatorSerializer(operator)

        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR FETCH ADMIN DETAILS ----- 
class AdminDetailsView(generics.RetrieveAPIView):
    queryset = CustomUser.objects.filter(role='admin')
    serializer_class = FullAdminSerializer
    permission_classes = [IsAdminUser]

    def post(self, request, *args, **kwags):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response({
                "code": 403,
                "messsage": "Access denied!, Only super admin can view admins details"
            },status=status.HTTP_403_FORBIDDEN)
        
        admin_id = request.data.get('admin_id')
        
        if not admin_id:
            return Response({"code": 104, "message": "Admin ID required"},status=status.HTTP_400_BAD_REQUEST)
        
        admin = get_object_or_404(CustomUser, id=admin_id, role= 'admin')
        serializer  = FullAdminSerializer(admin)

        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR FETCH ITEM LIST -----
class ItemListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminOnly]
    page_size = 50

    def post(self, request, *args, **kwargs):
        search_query = request.data.get("search").strip()
        item = CanteenItem.objects.all().order_by('name')

        if search_query:
            item = item.filter(
                Q(name__icontains=search_query) | Q(price__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(item, request, view=self)
        if result is not None:
            serializer = CanteenItemSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = CanteenItemSerializer(item, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---- API FOR DELETE ITEM -----
class DeleteItemView(APIView):
    permission_classes = [IsAdminOnly]
    def post(self, request, *args, **kwargs):
        try:
            item_id = request.data.get("item_id")
            if not item_id:
                return Response({"code" : 104, "message": "Card ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if card exists
            try:
                item = CanteenItem.objects.get(id=item_id)
            except CanteenItem.DoesNotExist:
                return Response({"code": 404, "message": "Card not found"}, status=status.HTTP_404_NOT_FOUND)

            # Delete the card
            item.delete()
            return Response({"message": "RFID Card deleted successfully.", "card_id": item_id}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})


# ----- API TO CREATE ITEM ----
class CreateItemView(generics.CreateAPIView):
    queryset = CanteenItem.objects.all()
    serializer_class = CanteenItemSerializer
    permission_classes = [IsAuthenticated]


# ----- API EDIT ITEM -----
class EditItemView(generics.UpdateAPIView):
    queryset = CanteenItem.objects.all()
    serializer_class = CanteenItemSerializer
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        # Only Admins can update any user
        if request.user.role != 'admin':
            return Response({"code": 403, "message": "Only admins can update users"}, status=status.HTTP_403_FORBIDDEN)
        
        # Extract `user_id` from request data
        item_id = request.data.get('item_id')

        if not item_id:
            return Response({"code" : 104, "message": "Item ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            item = CanteenItem.objects.get(id=item_id)
        except CanteenItem.DoesNotExist:
            return Response({"code": 404, "message": "Item not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        serializer.save()
        return Response({"message": "Item updated successfully", "item": serializer.data}, status=status.HTTP_200_OK)


# ---- API TO CREATE CARD ----
class CreateCardView(generics.CreateAPIView):
    queryset = RFIDCard.objects.all()
    serializer_class = CreateRFIDCardSerializer
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        try: 
            # Only admins can create users
            if request.user.role != 'admin':
                return Response({"code": 403, "message": "Access denied. Only can create new users"},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Check if student have a card
            student = request.data.get("student")
            if RFIDCard.objects.filter(student=student).exists():
                return Response({"code": 112, "message": "This student already have a card"},status=status.HTTP_400_BAD_REQUEST)
            
            # Check if card number already taken
            card_number = request.data.get("card_number")
            if RFIDCard.objects.filter(card_number=card_number).exists():
                return Response({"code": 105, "message": "This card number already exists"}, status=status.HTTP_400_BAD_REQUEST)
            
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            rfidcard = serializer.save() 

            return Response({
                    "message": f"{rfidcard.student.first_name} card created successfully", "rfidcard": serializer.data}
                    ,status=status.HTTP_201_CREATED
                )
        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"},status=status.HTTP_400_BAD_REQUEST)


# ---- API FOR EDIT CARD DETAILS ----  
class EditCardView(generics.UpdateAPIView):
    queryset = RFIDCard.objects.all()
    serializer_class = CreateRFIDCardSerializer
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        # Only Admins can update any user
        if request.user.role != 'admin':
            return Response({"code": 403, "message": "Only admins can update users"}, status=status.HTTP_403_FORBIDDEN)
        
        # Extract `user_id` from request data
        card_id = request.data.get('card_id')
        student = request.data.get('student')

        # Check if card number already taken
        card_number = request.data.get("card_number")
        if RFIDCard.objects.filter(card_number=card_number).exclude(student=student).exists():
            return Response({"code": 105, "message": "This card number already taken"}, status=status.HTTP_400_BAD_REQUEST)

        if not card_id:
            return Response({"code" : 104, "message": "Card ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            card = RFIDCard.objects.get(id=card_id)
        except RFIDCard.DoesNotExist:
            return Response({"code": 404, "message": "Card not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(card, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        serializer.save()
        return Response({"message": "User updated successfully", "user": serializer.data}, status=status.HTTP_200_OK)


# ---- API FOR DELETE CARD -----
class DeleteCardView(APIView):
    def post(self, request, *args, **kwargs):
        try:
            # Get card ID from request body
            # Get card ID from request body
            card_id = request.data.get("card_id")
            if not card_id:
                return Response({"code" : 104, "message": "Card ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if card exists
            try:
                rfid_card = RFIDCard.objects.get(id=card_id)
            except RFIDCard.DoesNotExist:
                return Response({"code": 404, "message": "Card not found"}, status=status.HTTP_404_NOT_FOUND)

            # Delete the card
            rfid_card.delete()
            return Response({"message": "RFID Card deleted successfully.", "card_id": card_id}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})


# ---- API FOR GET CARD LIST
class CardListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminUser]
    page_size = 50

    def post(self, request, *args, **kwargs):
        search_query = request.data.get("search").strip()
        card = RFIDCard.objects.all().order_by('card_number')

        if search_query:
            card = card.filter(
                Q(card_number__icontains=search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(card, request, view=self)
        if result is not None:
            serializer = RFIDCardSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = RFIDCardSerializer(card, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR FETCH CARD DETAILS ----- 
class CardDetailsView(generics.RetrieveAPIView):
    queryset = RFIDCard.objects.all()
    serializer_class = RFIDCardSerializer
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwags):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response({
                "code": 403,
                "messsage": "Access denied!, Only super admin can view admins details"
            },status=status.HTTP_403_FORBIDDEN)
        
        card_id = request.data.get('card_id')
        
        if not card_id:
            return Response({"code": 104, "message": "Card ID required"},status=status.HTTP_400_BAD_REQUEST)
        
        card = get_object_or_404(RFIDCard, id=card_id, role= 'admin')
        serializer  = RFIDCardSerializer(card)

        return Response(serializer.data, status=status.HTTP_200_OK)
    

# API FOR ACTIVATE AND DEACTIVATE CARD
class ActivateDeactivateCardView(APIView):
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        try:
            # Only Admins can update any user
            if request.user.role != 'admin':
                return Response({"code": 403, "message": "Only admins can update users"}, status=status.HTTP_403_FORBIDDEN)


            # Get card ID from request body
            card_id = request.data.get("card_id")
            if not card_id:
                return Response({"code" : 104, "message": "Card ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if card exists
            try:
                rfid_card = RFIDCard.objects.get(id=card_id)
            except RFIDCard.DoesNotExist:
                return Response({"code": 404, "message": "Card not found"}, status=status.HTTP_404_NOT_FOUND)

            # Toggle is_active based on request data
            action = request.data.get("action")  # Expected values: "activate" or "deactivate"
            if action == "activate":
                rfid_card.is_active = True
                message = "RFID Card activated successfully."
            elif action == "deactivate":
                rfid_card.is_active = False
                message = "RFID Card deactivated successfully."
            else:
                return Response({"code": 111, "message": "Invalid action. Use 'activate' or 'deactivate'."}, status=status.HTTP_400_BAD_REQUEST)

            rfid_card.save()
            return Response({"message": message, "card_id": card_id, "is_active": rfid_card.is_active}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})