from rest_framework import serializers

from smmsapp.models import JournalEntry, JournalLine


class JournalLineSerializer(serializers.ModelSerializer):
    account = serializers.CharField(source='account.code', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    rfid_card = serializers.UUIDField(source='rfid_card_id', read_only=True, allow_null=True)

    class Meta:
        model = JournalLine
        fields = ['id', 'account', 'account_name', 'rfid_card', 'direction', 'amount', 'balance_after']


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = ['id', 'event_type', 'memo', 'created_at', 'ref_transaction', 'ref_deposit', 'lines']


class CardStatementLineSerializer(serializers.ModelSerializer):
    event_type = serializers.CharField(source='entry.event_type', read_only=True)
    memo = serializers.CharField(source='entry.memo', read_only=True)
    account = serializers.CharField(source='account.code', read_only=True)
    entry_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = JournalLine
        fields = ['id', 'entry_id', 'event_type', 'memo', 'account', 'direction', 'amount', 'balance_after', 'created_at']


class TrialBalanceAccountSerializer(serializers.Serializer):
    account = serializers.CharField()
    name = serializers.CharField()
    debit = serializers.CharField()
    credit = serializers.CharField()
    net = serializers.CharField()


class TrialBalanceSerializer(serializers.Serializer):
    as_of = serializers.DateField(allow_null=True)
    accounts = TrialBalanceAccountSerializer(many=True)
