from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework import status, generics
from drf_spectacular.utils import extend_schema
from django_filters.rest_framework import DjangoFilterBackend
from ..models import SMSLog
from ..serializers.sms import SMSLogSerializer

@extend_schema(tags=['sms'])
class SMSOptOutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request={"type": "object", "properties": {"sms_opt_out": {"type": "boolean"}}}, responses={200: {"type": "object"}})
    def post(self, request):
        opt_out = request.data.get("sms_opt_out")
        if opt_out is None:
            return Response({"code": 400, "message": "sms_opt_out required"}, status=status.HTTP_400_BAD_REQUEST)
        request.user.sms_opt_out = bool(opt_out)
        request.user.save(update_fields=["sms_opt_out"])
        return Response({"sms_opt_out": request.user.sms_opt_out})

@extend_schema(tags=['sms'])
class SMSLogListView(generics.ListAPIView):
    serializer_class = SMSLogSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "provider"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = SMSLog.objects.select_related("recipient").all()
        phone = self.request.query_params.get("phone")
        if phone:
            qs = qs.filter(phone__icontains=phone)
        return qs
