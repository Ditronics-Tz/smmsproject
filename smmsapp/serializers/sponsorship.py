from decimal import Decimal

from rest_framework import serializers

from smmsapp.models import FundContribution, SponsorFund, SponsorshipAllocation


class SponsorFundSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    students_covered = serializers.SerializerMethodField()

    class Meta:
        model = SponsorFund
        fields = [
            'id', 'name', 'sponsor_name', 'contact', 'description', 'status',
            'start_date', 'end_date', 'alert_threshold', 'balance', 'students_covered',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'balance', 'students_covered']

    def validate_status(self, value):
        if value == 'closed':
            raise serializers.ValidationError('Use the close endpoint to close a fund.')
        return value

    def get_balance(self, obj) -> str:
        return f"{Decimal(getattr(obj, 'balance', Decimal('0.00'))):.2f}"

    def get_students_covered(self, obj) -> int:
        return getattr(obj, 'students_covered', 0)


class FundContributionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FundContribution
        fields = ['id', 'amount', 'method', 'reference', 'received_at', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        if not (attrs.get('reference') or '').strip():
            raise serializers.ValidationError({'reference': 'A reason or reference is required for every contribution.'})
        return attrs


class FundCloseSerializer(serializers.Serializer):
    disposition = serializers.ChoiceField(choices=['refund', 'transfer'])
    target_fund_id = serializers.IntegerField(required=False)
    reason = serializers.CharField(allow_blank=False)

    def validate(self, attrs):
        if attrs['disposition'] == 'transfer' and not attrs.get('target_fund_id'):
            raise serializers.ValidationError({'target_fund_id': 'A target fund is required for transfers.'})
        if attrs['disposition'] == 'refund' and attrs.get('target_fund_id'):
            raise serializers.ValidationError({'target_fund_id': 'Do not supply a target fund for refunds.'})
        return attrs


class AllocationSerializer(serializers.ModelSerializer):
    fund_id = serializers.IntegerField(write_only=True)
    student_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = SponsorshipAllocation
        fields = [
            'id', 'fund_id', 'student_id', 'meal_types', 'daily_cap', 'per_meal_cap',
            'valid_from', 'valid_to', 'priority', 'is_active',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        daily = attrs.get('daily_cap')
        per_meal = attrs.get('per_meal_cap')
        if daily is not None and per_meal is not None and per_meal > daily:
            raise serializers.ValidationError({'per_meal_cap': 'Per-meal cap cannot exceed daily cap.'})
        if attrs.get('valid_to') and attrs['valid_to'] < attrs['valid_from']:
            raise serializers.ValidationError({'valid_to': 'Must be on or after valid_from.'})
        valid_meals = {'breakfast', 'lunch', 'dinner'}
        meals = attrs.get('meal_types')
        if not isinstance(meals, list) or not meals or set(meals) - valid_meals:
            raise serializers.ValidationError({'meal_types': 'Supply one or more valid meal types.'})
        return attrs
