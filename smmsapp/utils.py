from django.utils.timezone import now
from io import BytesIO
from django.db.models import Sum, Q
from .models import Transaction, RFIDCard, ParentStudent
from weasyprint import HTML
from django.template.loader import render_to_string


def get_admin_scope(user):
    """Return the school an admin is scoped to, or None for global scope.

    An admin with `school` set is a school-admin and should only see that
    school's data. An admin with `school = None` (or any non-admin) returns
    None, meaning global access.
    """
    if user and getattr(user, 'role', None) == 'admin' and user.school_id:
        return user.school
    return None


def generate_end_of_day_report(school=None):
    buffer = BytesIO()
    today = now().date()

    # Scope transactions to a school when the admin is school-scoped.
    tx_filter = Q(transaction_date__date=today)
    card_filter = Q()
    if school is not None:
        tx_filter &= Q(student_or_staff__school=school)
        card_filter &= Q(student_or_staff__school=school)

    transactions = Transaction.objects.filter(tx_filter)

    total_sales = transactions.aggregate(Sum('amount'))['amount__sum'] or 0

    available_balance = RFIDCard.objects.filter(card_filter).aggregate(Sum('balance'))['balance__sum'] or 0
    start_balance = available_balance + total_sales
    remaining_balance = available_balance

    html_string = render_to_string("admin_report.html", {
        "today": today,
        "total_start_balance": start_balance,
        "total_expenditure": total_sales,
        "total_remaining_balance": remaining_balance,
        "transactions": transactions,
    })

    pdf = HTML(string=html_string).write_pdf()
    buffer.write(pdf)
    buffer.seek(0)

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
        available_balance = RFIDCard.objects.filter(student_or_staff=student.student).aggregate(Sum('balance'))['balance__sum'] or 0
        expenditure = Transaction.objects.filter(transaction_date__date=today, student_or_staff=student.student).aggregate(Sum('amount'))['amount__sum'] or 0
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
    transactions = Transaction.objects.filter(transaction_date__date=today, student_or_staff__in=[s.student for s in students])
    total_debt = transactions.filter(transaction_status="penalty").aggregate(Sum('amount'))['amount__sum'] or 0

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
