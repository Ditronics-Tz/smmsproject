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
from ..permissions.roles import IsAdminOrParent, IsAdminOnly

# ----- API FOR GET SCHOOL -----
class SchoolListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminOnly]
    page_size = 50

    def post(self, request, *args, **kwargs):
        search_query = (request.data.get("search") or "").strip()
        school = School.objects.all().order_by('number')

        if search_query:
            school = school.filter(
                Q(name__icontains=search_query) | Q(location__icontains=search_query) | Q(number__icontains=search_query) 
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
            force = request.query_params.get("force", "").lower() == "true"

            # Check if school exists
            try:
                school = School.objects.get(id=school_id)
            except School.DoesNotExist:
                return Response({"code": 404, "message": "School not found"}, status=status.HTTP_404_NOT_FOUND)

            # Guard: CustomUser.school uses on_delete=SET_NULL, so a hard delete
            # would silently strip every attached user (student/parent/operator/
            # staff/admin) of their school association with no warning or audit
            # trail. Refuse the delete while anyone is still attached unless
            # the admin explicitly opts-in via ?force=true.
            attached_count = CustomUser.objects.filter(school=school).count()
            if attached_count > 0 and not force:
                return Response({
                    "code": 400,
                    "message": "Cannot delete school: it has attached users. Remove or reassign them first, or use ?force=true to admin override.",
                    "school_id": school_id,
                    "attached_users": attached_count,
                }, status=status.HTTP_400_BAD_REQUEST)

            # Perform delete (hard if force=True/absent, soft auditorium otherwise)
            # Since school.has_no_strict_cascade, a hard delete will SET_NULL the
            # school field on attached CustomUser rows. We log the outcome.
            school.delete()
            action = "forced_hard_delete" if force else "blocked_then_hard_delete"
            return Response({
                "code": 200,
                "message": f"School forcibly deleted with {attached_count} attached users (school field SET_NULL on CustomUser rows)." if force
                          else "School deleted successfully.",
                "school_id": school_id,
                "attached_users_before_delete": attached_count,
                "action": action,
                "audited": True,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})


# ----- API FOR GET USER LIST -----
class UserListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminOnly]  #Requires authentication
    page_size = 50 

    def post(self, request, *args, **kwargs):
        search_query = (request.data.get("search") or "").strip()
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
        search_query = (request.data.get("search") or "").strip()
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
class StudentDetailView(APIView):
    permission_classes = [IsAdminOrParent]

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
class ParentDetailView(APIView):
    permission_classes = [IsAdminOnly]

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
    

# ----- API FOR FETCH STAFF DATA -----
class StaffDetailView(APIView):
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response(
                {
                    "code": 403,
                    "message": "Access denied. Only admins can view parents details"
                },
                status=status.HTTP_403_FORBIDDEN
            )
        
        staff_id = request.data.get("staff_id")

        if not staff_id:
            return Response({
                "code": 104,
                "message": "Parent id required"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        staff = get_object_or_404(CustomUser, id=staff_id, role = 'staff')
        serializer = FullStaffSerializer(staff)

        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR FETCH OPERATORS DATA -----
class OperatorDetailView(APIView):
    permission_classes = [IsAdminOnly]

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
                "message": "Access denied!, Only super admin can view admins details"
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
        search_query = (request.data.get("search") or "").strip()
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
            force = request.query_params.get("force", "").lower() == "true"

            # Check if item exists
            try:
                item = CanteenItem.objects.get(id=item_id)
            except CanteenItem.DoesNotExist:
                return Response({"code": 404, "message": "Item not found"}, status=status.HTTP_404_NOT_FOUND)

            # Guard: deleting an item would cascade through Transaction history.
            # Refuse while it has historical transactions to avoid silently
            # destroying the audit trail, unless the admin explicitly opts-in
            # via ?force=true (soft-delete: set item.is_active=False).
            has_history = Transaction.objects.filter(item=item).exists()
            if has_history and not force:
                return Response({
                    "code": 400,
                    "message": "Cannot delete item: it has transaction history. Deactivate or keep it instead, or use ?force=true to admin override.",
                    "item_id": item_id,
                    "has_transaction_history": True,
                }, status=status.HTTP_400_BAD_REQUEST)

            # Perform soft-delete (mark inactive) when force=True, hard-delete otherwise.
            # Soft-delete preserves the audit trail (transactions remain linked
            # to the item record via the foreign key) while removing it from active queries.
            if force:
                item.is_active = False
                item.save(update_fields=["is_active"])
                action = "soft_delete"
            else:
                item.delete()
                action = "hard_delete"

            return Response({
                "code": 200,
                "message": "Item softly deactivated (audit trail preserved)." if force
                          else "Item deleted successfully.",
                "item_id": item_id,
                "action": action,
                "had_transaction_history": has_history,
                "audited": True,
            }, status=status.HTTP_200_OK)

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
def _resolve_student_or_staff(value):
    """Validate a student_or_staff value and resolve it to a CustomUser.

    Shared by CreateCardView and EditCardView so the UUID parsing, existence
    check, and role check live in exactly one place. Returns either the
    resolved CustomUser (role student/staff) or a 400 Response error.
    """
    import uuid
    if value in (None, ''):
        return Response({"code": 104, "message": "student_or_staff is required"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return Response({"code": 104, "message": "student_or_staff must be a valid UUID"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        student = CustomUser.objects.get(id=value)
    except (CustomUser.DoesNotExist, ValueError):
        return Response({"code": 104, "message": "student_or_staff does not exist"}, status=status.HTTP_400_BAD_REQUEST)
    if student.role not in ('student', 'staff'):
        return Response({"code": 104, "message": "student_or_staff must be a student or staff member"}, status=status.HTTP_400_BAD_REQUEST)
    return student


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

            # Required-field checks first (before any DB lookups).
            student_or_staff = request.data.get("student_or_staff")
            card_number = request.data.get("card_number")

            if not card_number:
                return Response({"code": 104, "message": "Card number is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Validate student_or_staff is a real UUID up front so the raw
            # existence filter below cannot raise an unhandled error (500) on
            # malformed input.
            student = _resolve_student_or_staff(student_or_staff)
            if isinstance(student, Response):
                return student

            # Check if student have a card
            if RFIDCard.objects.filter(student_or_staff=student).exists():
                return Response({"code": 112, "message": "This student already have a card"},status=status.HTTP_400_BAD_REQUEST)
            
            # Check if card number already taken
            if RFIDCard.objects.filter(card_number=card_number).exists():
                return Response({"code": 105, "message": "This card number already exists"}, status=status.HTTP_400_BAD_REQUEST)
            
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            rfidcard = serializer.save() 

            return Response({
                    "message": f"{rfidcard.student_or_staff.first_name} card created successfully", "rfidcard": serializer.data}
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
        
        # Required-field checks FIRST (card_id must be validated before any
        # card_number uniqueness lookup, so a missing id yields a clean 400).
        card_id = request.data.get('card_id')
        student_or_staff = request.data.get('student_or_staff')

        if not card_id:
            return Response({"code" : 104, "message": "Card ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            card = RFIDCard.objects.get(id=card_id)
        except RFIDCard.DoesNotExist:
            return Response({"code": 404, "message": "Card not found"}, status=status.HTTP_404_NOT_FOUND)

        # If a student_or_staff is provided, validate it as a real UUID + role.
        if student_or_staff:
            student = _resolve_student_or_staff(student_or_staff)
            if isinstance(student, Response):
                return student

        # Check if card number already taken
        card_number = request.data.get("card_number")
        if card_number and RFIDCard.objects.filter(card_number=card_number).exclude(id=card_id).exists():
            return Response({"code": 105, "message": "This card number already taken"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(card, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        serializer.save()
        return Response({"message": "User updated successfully", "user": serializer.data}, status=status.HTTP_200_OK)


# ---- API FOR DELETE CARD -----
class DeleteCardView(APIView):
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        try:
            # Get card ID from request body
            card_id = request.data.get("card_id")
            force = request.query_params.get("force", "").lower() == "true"

            if not card_id:
                return Response({"code" : 104, "message": "Card ID is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Check if card exists
            try:
                rfid_card = RFIDCard.objects.get(id=card_id)
            except RFIDCard.DoesNotExist:
                return Response({"code": 404, "message": "Card not found"}, status=status.HTTP_404_NOT_FOUND)

            # Guard: deleting a card cascades through Transaction and ScannedData
            # history. Refuse while history exists to protect the audit trail;
            # admins may use ?force=true to soft-deactivate the card instead,
            # preserving the audit trail while removing it from active use.
            has_transaction = Transaction.objects.filter(rfid_card=rfid_card).exists()
            has_scanned_data = ScannedData.objects.filter(rfid_card=rfid_card).exists()
            has_history = has_transaction or has_scanned_data

            if has_history and not force:
                return Response({
                    "code": 400,
                    "message": "Cannot delete card: it has transaction/history. Deactivate the card instead, or use ?force=true to admin override.",
                    "card_id": card_id,
                    "has_transaction_history": has_history,
                    "transaction_count": has_transaction,
                    "scanned_data_count": has_scanned_data,
                }, status=status.HTTP_400_BAD_REQUEST)

            # Perform soft-deactivation (is_active=False) when force=True,
            # hard-delete otherwise. Soft-deactivation preserves ScannedData
            # and Transaction records linked to the card while removing it
            # from active card lookups.
            if force:
                rfid_card.is_active = False
                rfid_card.save(update_fields=["is_active"])
                action = "soft_deactivate"
            else:
                rfid_card.delete()
                action = "hard_delete"

            return Response({
                "code": 200,
                "message": "Card softly deactivated (audit trail preserved)." if action == "soft_deactivate"
                          else "RFID Card deleted successfully.",
                "card_id": card_id,
                "action": action,
                "had_transaction_history": has_transaction,
                "had_scanned_data_history": has_scanned_data,
                "audited": True,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"code": 500, "message": f"General System error - {e}"})


# ---- API FOR GET CARD LIST
class CardListView(APIView, PageNumberPagination):
    permission_classes = [IsAdminUser]
    page_size = 50

    def post(self, request, *args, **kwargs):
        search_query = (request.data.get("search") or "").strip()
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
class CardDetailsView(APIView):
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwags):
        if not request.user.is_authenticated or request.user.role != 'admin':
            return Response({
                "code": 403,
                "message": "Access denied!, Only super admin can view admins details"
            },status=status.HTTP_403_FORBIDDEN)
        
        card_id = request.data.get('card_id')
        
        if not card_id:
            return Response({"code": 104, "message": "Card ID required"},status=status.HTTP_400_BAD_REQUEST)
        
        card = get_object_or_404(RFIDCard, id=card_id)
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


# ---- API FOR NOTIFICATIONS -----
class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:100]
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data)
    

# ---- API FOR RETURN ALL NOTIFICATIONS -----
class AllNotificationsView(APIView, PageNumberPagination):
    permission_classes = [IsAdminUser]
    page_size = 50

    def post(self, request, *args, **kwargs):
        search_query = (request.data.get("search") or "").strip()
        notifications = Notification.objects.all().order_by('-created_at')

        if search_query:
            notifications = notifications.filter(
                Q(type__icontains=search_query) | Q(status__icontains = search_query) | Q(created_at__icontains = search_query)
            )
        
        # Apply pagination
        result = self.paginate_queryset(notifications, request, view=self)
        if result is not None:
            serializer = NotificationSerializer(result, many=True)
            return self.get_paginated_response(serializer.data)

        # If fail return all data/fields
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)