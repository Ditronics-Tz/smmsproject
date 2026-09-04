from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..permissions.roles import IsAdminOrParent
from ..serializers.alerts import BalanceThresholdSerializer
from ..services.audit import log_action, snapshot
from ..services.alerts import _effective_threshold


class BalanceThresholdView(APIView):
    """Parent can view and update their low-balance alert threshold.

    GET returns the effective threshold (explicit value or system default).
    PUT accepts balance_threshold (decimal) or null to reset to the default.
    """
    permission_classes = [IsAdminOrParent]

    def _enforce_parent(self, request):
        if request.user.role != 'parent':
            return Response(
                {'code': 403, 'message': 'Access denied. Only parents can configure this.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def get(self, request):
        blocked = self._enforce_parent(request)
        if blocked:
            return blocked
        serializer = BalanceThresholdSerializer({
            'balance_threshold': request.user.balance_threshold,
            'effective_threshold': _effective_threshold(request.user),
        })
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        blocked = self._enforce_parent(request)
        if blocked:
            return blocked

        serializer = BalanceThresholdSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        value = serializer.validated_data.get('balance_threshold')
        user = request.user
        # Treat an explicit integer/None from the client via SerializerField.
        before_thr = snapshot(user)
        user.balance_threshold = value
        user.save(update_fields=['balance_threshold'])
        try:
            log_action('update', obj=user, before=before_thr, after=snapshot(user))
        except Exception:
            pass

        response_serializer = BalanceThresholdSerializer({
            'balance_threshold': user.balance_threshold,
            'effective_threshold': _effective_threshold(user),
        })
        return Response(response_serializer.data, status=status.HTTP_200_OK)
