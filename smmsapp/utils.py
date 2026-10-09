from django.utils.timezone import now
from io import BytesIO
from django.db.models import Sum, Q
from .models import Transaction, RFIDCard, ParentStudent
from django.template.loader import render_to_string


def _html_to_pdf(html_string):
    """Render HTML string to PDF bytes.

    WeasyPrint is imported lazily so the app can boot on machines without
    its native system libraries (Pango/Cairo); only PDF generation fails
    there, everything else works.
    """
    from weasyprint import HTML
    return HTML(string=html_string).write_pdf()


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

    from .services.transaction_metrics import with_payment_revenue
    transactions = list(with_payment_revenue(Transaction.objects.filter(
        tx_filter, is_voided=False, transaction_status__in=['successful', 'penalty'],
    ).select_related('item').prefetch_related('payment_parts')))
    for txn in transactions:
        txn.sponsor_paid = sum((part.amount for part in txn.payment_parts.all() if part.source == 'fund'), 0)
        txn.wallet_paid = txn.charged_amount
    total_sales = sum((txn.payment_revenue for txn in transactions), 0)
    sponsor_paid = sum((txn.sponsor_paid for txn in transactions), 0)
    wallet_sales = sum((txn.wallet_paid for txn in transactions), 0)

    available_balance = RFIDCard.objects.filter(card_filter).aggregate(Sum('balance'))['balance__sum'] or 0
    start_balance = available_balance + wallet_sales
    remaining_balance = available_balance

    html_string = render_to_string("admin_report.html", {
        "today": today,
        "total_start_balance": start_balance,
        "total_expenditure": total_sales,
        "sponsor_paid": sponsor_paid,
        "total_remaining_balance": remaining_balance,
        "transactions": transactions,
    })

    pdf = _html_to_pdf(html_string)
    buffer.write(pdf)
    buffer.seek(0)

    return buffer

def generate_parent_end_of_day_report(request):
    buffer = BytesIO()
    today = now().date()
    from .services.transaction_metrics import with_payment_revenue

    students = ParentStudent.objects.filter(parent=request.user)

    student_data = []
    total_start_balance = 0
    total_expenditure = 0
    total_remaining_balance = 0

    for student in students:
        available_balance = RFIDCard.objects.filter(student_or_staff=student.student).aggregate(Sum('balance'))['balance__sum'] or 0
        student_txns = Transaction.objects.filter(
            transaction_date__date=today, student_or_staff=student.student,
            is_voided=False, transaction_status__in=['successful', 'penalty'],
        )
        student_txns = with_payment_revenue(student_txns)
        student_txns = list(student_txns.prefetch_related('payment_parts'))
        for txn in student_txns:
            txn.sponsor_paid = sum((part.amount for part in txn.payment_parts.all() if part.source == 'fund'), 0)
            txn.wallet_paid = txn.charged_amount
        expenditure = sum((txn.payment_revenue for txn in student_txns), 0)
        wallet_expenditure = sum((txn.wallet_paid for txn in student_txns), 0)
        start_balance = available_balance + wallet_expenditure
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
    transactions = list(Transaction.objects.filter(
        transaction_date__date=today, student_or_staff__in=[s.student for s in students],
        is_voided=False, transaction_status__in=['successful', 'penalty'],
    ).prefetch_related('payment_parts'))
    for txn in transactions:
        txn.sponsor_paid = sum((part.amount for part in txn.payment_parts.all() if part.source == 'fund'), 0)
        txn.wallet_paid = txn.charged_amount
    total_debt = sum((
        (txn.amount - txn.item.price) if txn.payment_parts.all() else txn.charged_amount
        for txn in transactions if txn.transaction_status == 'penalty'
    ), 0)

    # Render the HTML template
    html_string = render_to_string("parent_report.html", {
        "today": today,
        "student_data": student_data,
        "total_start_balance": total_start_balance,
        "total_expenditure": total_expenditure,
        "total_remaining_balance": total_remaining_balance,
        "total_debt": total_debt,
        "sponsor_paid": sum((txn.sponsor_paid for txn in transactions), 0),
        "transactions": transactions,
    })

    # Convert HTML to PDF
    pdf = _html_to_pdf(html_string)
    buffer.write(pdf)
    buffer.seek(0)  # Move buffer cursor to the start
    
    return buffer
