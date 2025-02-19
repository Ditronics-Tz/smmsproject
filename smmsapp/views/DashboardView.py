from django.db.models import Sum, Count
from django.http import FileResponse
from django.utils.timezone import now, timedelta
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny, DjangoModelPermissionsOrAnonReadOnly, IsAuthenticated, IsAdminUser

from ..serializers.ResourceSerializers import FullStudentSerializer, StudentSerializer

from ..utils import generate_end_of_day_report, generate_parent_end_of_day_report
from ..models import ParentStudent, RFIDCard, Transaction, CustomUser, ScanSession, ScannedData
from ..serializers.DashboardSerializer import *
from ..permissions.CustomPermissions import IsAdminOrParent, IsAdminOnly, IsOperator, IsAdminOrOperator

#  ----- API FOR COUNTS IN DASHBOARD ------
class CountsView(APIView):
    permission_classes = [IsAdminOrOperator]

    def post(self, request, *args, **kwargs):
        today = now().date()
        week_start = today - timedelta(days=today.weekday())  # Get Monday of the current week
        
        total_students = CustomUser.objects.filter(role='student').count()
        total_parents = CustomUser.objects.filter(role='parent').count()
        total_available_balance = RFIDCard.objects.aggregate(total_balance=Sum('balance'))['total_balance'] or 0
        total_transactions = Transaction.objects.count() 

        total_price_today = 0
        total_price_week = 0

        total_sessions = 0

        if request.user.role == 'operator':
            # Get total sessions
            total_sessions = ScanSession.objects.filter(operator=request.user).count()
            # Get total price of items scanned by the operator TODAY
            total_price_today = ScannedData.objects.filter(
                session__operator=request.user,
                scanned_at__date=today
            ).aggregate(total_price=Sum('item__price'))['total_price'] or 0

            # Get total price of items scanned by the operator THIS WEEK
            total_price_week = ScannedData.objects.filter(
                session__operator=request.user,
                scanned_at__date__gte=week_start  # Get from Monday of this week till today
            ).aggregate(total_price=Sum('item__price'))['total_price'] or 0
            

        data = {
            "total_students": total_students,
            "total_parents": total_parents,
            "total_available_balance": total_available_balance,
            "total_transactions": total_transactions,
            "sessions": total_sessions,
            "price_week": total_price_week,
            "price_today": total_price_today,
        }

        serializer = CountsSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR SALES SUMMARY ------
class SalesSummaryView(APIView):
    permission_classes = [IsAdminOnly]

    def post(self, request,  *args, **kwargs):
        filter_type = request.data.get('filter', 'day')  # Default is 'day'
        today = now().date()

        if filter_type == 'day':
            start_date = today
        elif filter_type == 'month':
            start_date = today.replace(day=1)
        elif filter_type == 'year':
            start_date = today.replace(month=1, day=1)
        else:
            return Response({"error": "Invalid filter. Use 'day', 'month', or 'year'."}, status=status.HTTP_400_BAD_REQUEST)

        total_success = Transaction.objects.filter(transaction_date__date__gte=start_date, transaction_status='successful').count()
        total_penalts = Transaction.objects.filter(transaction_date__date__gte=start_date, transaction_status='penalt').count()
        total_success_amount = Transaction.objects.filter(transaction_date__date__gte=start_date, transaction_status='successful') \
                                         .aggregate(total_amount=Sum('amount'))['total_amount'] or 0
        total_penalt_amount = Transaction.objects.filter(transaction_date__date__gte=start_date, transaction_status='penalt') \
                                         .aggregate(total_amount=Sum('amount'))['total_amount'] or 0

        data = {
            "total_success": total_success,
            "total_penalts": total_penalts,
            "total_success_amount": total_success_amount,
            "total_penalts_amount": total_penalt_amount,
            "filter_type": filter_type
        }

        serializer = SalesSummarySerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ----- API FOR WEEKLY SALES TRANS --------
class WeeklySalesTrendView(APIView):
    permission_classes = [IsAdminOnly]

    def post(self, request,  *args, **kwargs):
        today = now().date()
        start_date = today - timedelta(days=6)  # Get data for the past 7 days

        sales_data = Transaction.objects.filter(transaction_date__date__gte=start_date, transaction_status='successful') \
                                        .values('transaction_date__date') \
                                        .annotate(sales_amount=Sum('amount')) \
                                        .order_by('transaction_date__date')

        formatted_sales_data = [
            {
                "date": entry['transaction_date__date'],
                "sales_amount": entry['sales_amount']
            }
            for entry in sales_data
        ]

        serializer = WeeklySalesSerializer(formatted_sales_data, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    

# ---- API FOR GET REPORT --------
class EndOfDayReportView(APIView):
    """Generate and download End-of-Day report"""
    permission_classes = [IsAdminOrParent]  # Only Admins can access

    def get(self, request):
        pdf_buffer = None
        if request.user.role == "admin":
            pdf_buffer = generate_end_of_day_report()
        elif request.user.role == "parent":
            pdf_buffer = generate_parent_end_of_day_report(request)
        else:
            return Response({"code": 403, "message": "Access denied. Only can create new users"},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        return FileResponse(pdf_buffer, as_attachment=True, filename="SMMS_Day_report.pdf")
    

# ----- API FOR LAST SESSION DETAILS ------
class LastSessionDetailsView(APIView):
    """API to return the last session details for an operator."""
    permission_classes = [IsOperator]

    def post(self, request):
        # Ensure user is an operator
        if request.user.role != "operator":
            return Response({"code": 403, "message": "Access denied. Only operators can view this."}, status=status.HTTP_403_FORBIDDEN)

        # Get the last session of the operator
        last_session = ScanSession.objects.filter(operator=request.user).order_by('-start_at').first()

        if not last_session:
            return Response({"code": 404, "message": "No sessions found for this operator."}, status=status.HTTP_404_NOT_FOUND)

        # Get all scanned data for the last session
        scanned_data = ScannedData.objects.filter(session=last_session)

        # Calculate total price of items in last session
        total_price = scanned_data.aggregate(Sum('item__price'))['item__price__sum'] or 0

        # Count number of students scanned
        student_count = scanned_data.values('student').distinct().count()

        return Response({
            "session_id": str(last_session.id),
            "session_type": last_session.type,
            "session_status": last_session.status,
            "start_time": last_session.start_at,
            "end_time": last_session.end_at,
            "total_price": total_price,
            "student_count": student_count
        }, status=status.HTTP_200_OK)
    

# API FOR RETURN PARENT'S STUDENT DETAILS
class ParentStudentsView(APIView):
    permission_classes = [IsAdminOrParent]

    def get(self, request):
        # Ensure user is a parent
        if request.user.role != "parent":
            return Response({"code": 403,"message": "Access denied. Only parents can access this."}, status=status.HTTP_403_FORBIDDEN)

        # Get all students linked to the parent
        parent_students = ParentStudent.objects.filter(parent=request.user)
        students = [ps.student for ps in parent_students]

        # Serialize the student data
        serializer = FullStudentSerializer(students, many=True)

        return Response(serializer.data, status=status.HTTP_403_FORBIDDEN)