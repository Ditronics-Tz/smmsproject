from django.utils.timezone import now
from io import BytesIO
from django.db.models import Sum
from .models import Transaction, RFIDCard, ParentStudent
from weasyprint import HTML
from django.template.loader import render_to_string

def generate_end_of_day_report():
    buffer = BytesIO()
    today = now().date()
    
    # Get all successful transactions for today
    transactions = Transaction.objects.none() # make sure to not get null

    transactions |= Transaction.objects.filter(transaction_date__date=today)

    # Calculate sales data
    total_sales = transactions.aggregate(Sum('amount'))['amount__sum'] or 0

    # Start Balance
    available_balance = RFIDCard.objects.aggregate(Sum('balance'))['balance__sum'] or 0
    start_balance = available_balance + total_sales  # Example, modify based on business logic

    # Calculate remaining balance
    remaining_balance = available_balance

    # Render the HTML template
    html_string = render_to_string("admin_report.html", {
        "today": today,
        "total_start_balance": start_balance,
        "total_expenditure": total_sales,
        "total_remaining_balance": remaining_balance,
        "transactions": transactions,
    })

    # Convert HTML to PDF
    pdf = HTML(string=html_string).write_pdf()
    buffer.write(pdf)
    buffer.seek(0)  # Move buffer cursor to the start
    
    return buffer

def generate_parent_end_of_day_report(request):
    buffer = BytesIO()
    today = now().date()

    students = ParentStudent.objects.filter(parent=request.user)

    student_data = []
    total_start_balance = 0
    total_expenditure = 0
    total_remaining_balance = 0

    for student in students:
        available_balance = RFIDCard.objects.filter(student=student.student).aggregate(Sum('balance'))['balance__sum'] or 0
        expenditure = Transaction.objects.filter(transaction_date__date=today, student=student.student).aggregate(Sum('amount'))['amount__sum'] or 0
        start_balance = available_balance + expenditure
        remaining_balance = available_balance

        student_data.append({
            "name": f"{student.student.first_name} {student.student.last_name}",
            "start_balance": start_balance,
            "expenditure": expenditure,
            "remaining_balance": remaining_balance
        })

        total_start_balance += start_balance
        total_expenditure += expenditure
        total_remaining_balance += remaining_balance

    # Get all transactions for today for all children
    transactions = Transaction.objects.filter(transaction_date__date=today, student__in=[s.student for s in students])
    total_debt = transactions.filter(transaction_status="penalt").aggregate(Sum('amount'))['amount__sum'] or 0

    # Render the HTML template
    html_string = render_to_string("parent_report.html", {
        "today": today,
        "student_data": student_data,
        "total_start_balance": total_start_balance,
        "total_expenditure": total_expenditure,
        "total_remaining_balance": total_remaining_balance,
        "total_debt": total_debt,
        "transactions": transactions,
    })

    # Convert HTML to PDF
    pdf = HTML(string=html_string).write_pdf()
    buffer.write(pdf)
    buffer.seek(0)  # Move buffer cursor to the start
    
    return buffer
