from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from django.utils.timezone import now
from io import BytesIO
from django.db.models import Sum
from .models import Transaction, RFIDCard

def generate_end_of_day_report():
    buffer = BytesIO()
    today = now().date()
    
    # Get all successful transactions for today
    transactions = Transaction.objects.filter(transaction_date__date=today)

    # Calculate sales data
    total_sales = transactions.aggregate(Sum('amount'))['amount__sum'] or 0

    # Start Balance
    available_balance = RFIDCard.objects.aggregate(Sum('balance'))['balance__sum']
    start_balance = available_balance + total_sales  # Example, modify based on business logic

    # Calculate remaining balance
    remaining_balance = start_balance - total_sales

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
    pdf.drawString(50, 610, "S/N")  # Adding Serial Number column
    pdf.drawString(100, 610, "Student Name")  # Adding Student Name column
    pdf.drawString(220, 610, "Item")
    pdf.drawString(315, 610, "Time")
    pdf.drawString(410, 610, "Amount")
    pdf.drawString(510, 610, "Status")

    y = 590
    pdf.setFont("Helvetica", 10)
    serial_number = 1  # Initialize serial number

    for transaction in transactions:
        # Draw the serial number, student name, item, time, amount, and status
        pdf.drawString(50, y, str(serial_number))  # Serial number
        pdf.drawString(100, y, f"{transaction.student.first_name} {transaction.student.last_name}")  # Student Name
        pdf.drawString(220, y, str(transaction.item.name))  # Item
        pdf.drawString(315, y, str(transaction.transaction_date.strftime("%H:%M:%S")))  # Time
        pdf.drawString(410, y, f"{transaction.amount:.2f}")  # Amount
        pdf.drawString(510, y, transaction.transaction_status.capitalize())  # Status
    
        # Increment serial number and move to next row
        serial_number += 1
        y -= 20
    
        if y < 50:  # Start new page if needed
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = 750

    pdf.save()
    buffer.seek(0)
    return buffer
