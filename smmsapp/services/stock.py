from smmsapp.models import StockLevel, StockMovement


def consume_stock(item, *, actor=None, enforce=False):
    """Consume one unit if a stock row exists; caller must be in atomic()."""
    level = StockLevel.objects.select_for_update().filter(item=item).first()
    if level is None:
        return True if not enforce else False
    if level.quantity <= 0:
        return True if not enforce else False
    level.quantity -= 1
    level.save(update_fields=['quantity', 'updated_at'])
    return StockMovement.objects.create(item=item, delta=-1, reason='Meal scan', created_by=actor)


def restore_stock(item, *, transaction_record, actor=None, reason='Transaction reversal'):
    """Restore one unit after reversing a meal scan; caller must be in atomic()."""
    consumed = StockMovement.objects.filter(source_transaction=transaction_record, delta=-1).exists()
    already_restored = StockMovement.objects.filter(source_transaction=transaction_record, delta=1).exists()
    if not consumed or already_restored:
        return False
    level = StockLevel.objects.select_for_update().filter(item=item).first()
    if level is None:
        return False
    level.quantity += 1
    level.save(update_fields=['quantity', 'updated_at'])
    StockMovement.objects.create(
        item=item, delta=1, reason=reason, created_by=actor, source_transaction=transaction_record,
    )
    return True
