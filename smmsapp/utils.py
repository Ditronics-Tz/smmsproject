from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from django.utils.timezone import now
from io import BytesIO
from django.db.models import Sum
from .models import Transaction

def generate_end_of_day_report():
    buffer = BytesIO()
    today = now().date()
    
    # Get all successful transactions for today
    transactions = Transaction.objects.filter(transaction_date__date=today, transaction_status="successful")

    # Calculate sales data
    total_sales = transactions.aggregate(Sum('amount'))['amount__sum'] or 0

    # Assume start balance (fetch from another model if needed)
    start_balance = 10000  # Example, modify based on business logic

    # Calculate remaining balance
    remaining_balance = start_balance + total_sales

    # Create PDF
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setTitle(f"End of Day Report - {today}")
    
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(200, 750, "End of Day Report")
    
    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, 720, f"Date: {today}")
    pdf.drawString(50, 700, f"Start Balance: {start_balance:.2f}")
    pdf.drawString(50, 680, f"Total Sales: {total_sales:.2f}")
    pdf.drawString(50, 660, f"Remaining Balance: {remaining_balance:.2f}")
    
    # Table Header
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, 630, "Transactions:")
    pdf.drawString(50, 610, "ID")
    pdf.drawString(150, 610, "Time")
    pdf.drawString(250, 610, "Amount")
    pdf.drawString(350, 610, "Status")

    y = 590
    pdf.setFont("Helvetica", 10)
    for transaction in transactions:
        pdf.drawString(50, y, str(transaction.id))
        pdf.drawString(150, y, str(transaction.transaction_date.time()))
        pdf.drawString(250, y, f"{transaction.amount:.2f}")
        pdf.drawString(350, y, transaction.transaction_status.capitalize())
        y -= 20
        if y < 50:  # Start new page if needed
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = 750

    pdf.save()
    buffer.seek(0)
    return buffer
