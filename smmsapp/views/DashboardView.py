from django.db.models import Sum, Count
from django.http import FileResponse
from django.utils.timezone import now, timedelta
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny, DjangoModelPermissionsOrAnonReadOnly, IsAuthenticated, IsAdminUser

from ..utils import generate_end_of_day_report, generate_parent_end_of_day_report
from ..models import RFIDCard, Transaction, CustomUser, ScanSession, ScannedData
from ..serializers.DashboardSerializer import *
from ..permissions.CustomPermissions import IsAdminOrParent, IsAdminOnly

#  ----- API FOR COUNTS IN DASHBOARD ------
class CountsView(APIView):
    permission_classes = [IsAdminOnly]

    def post(self, request, *args, **kwargs):
        total_students = CustomUser.objects.filter(role='student').count()
        total_parents = CustomUser.objects.filter(role='parent').count()
        total_available_balance = RFIDCard.objects.aggregate(total_balance=Sum('balance'))['total_balance'] or 0
        total_transactions = Transaction.objects.count()

        sessions = 0
        if request.user.role == 'operator':
            sessions = ScanSession.objects.filter(operator=request.user).count()
        else:
            sessions = ScanSession.objects.count()

        data = {
            "total_students": total_students,
            "total_parents": total_parents,
            "total_available_balance": total_available_balance,
            "total_transactions": total_transactions,
            "sessions": sessions
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