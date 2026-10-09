from django.db.models import Case, DecimalField, Exists, F, OuterRef, Subquery, Sum, When
from django.db.models.functions import Coalesce


def with_payment_revenue(queryset):
    """Annotate gross meal value; legacy rows fall back to charged_amount."""
    from smmsapp.models import TransactionPayment
    totals = TransactionPayment.objects.filter(transaction_id=OuterRef('pk')).values('transaction_id').annotate(
        amount=Sum('amount'),
    ).values('amount')[:1]
    money = DecimalField(max_digits=14, decimal_places=2)
    return queryset.annotate(has_payment_parts=Exists(TransactionPayment.objects.filter(transaction_id=OuterRef('pk')))).annotate(payment_revenue=Coalesce(
        Subquery(totals, output_field=money), F('charged_amount'), output_field=money,
    ))


def penalty_charge_expression():
    """Use the recorded fee for new split-pay rows; preserve legacy semantics.

    Apply this expression to a queryset passed through ``with_payment_revenue``.
    """
    money = DecimalField(max_digits=14, decimal_places=2)
    return Case(
        When(has_payment_parts=True, then=F('amount') - F('item__price')),
        default=F('charged_amount'), output_field=money,
    )
