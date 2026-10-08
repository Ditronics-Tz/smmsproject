from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from smmsapp.models import FeatureFlag
from smmsapp.serializers.features import FeatureFlagSerializer, FeatureFlagUpdateSerializer
from smmsapp.services.audit import log_action, snapshot
from smmsapp.services.features import all_flags


class PublicConfigView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response({
            'app_name': settings.APP_NAME,
            'short_name': settings.SHORT_NAME,
            'currency': {
                'code': settings.CURRENCY_CODE,
                'symbol': settings.CURRENCY_SYMBOL,
                'decimals': settings.CURRENCY_DECIMALS,
            },
            'locale': settings.APP_LOCALE,
        })


class FeaturesConfigView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response({'features': all_flags()})


class FeatureFlagUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=FeatureFlagUpdateSerializer, responses={200: FeatureFlagSerializer})
    def put(self, request, key):
        if not request.user.is_superuser:
            return Response({'detail': 'Superuser access required.'}, status=status.HTTP_403_FORBIDDEN)
        if key not in getattr(settings, 'FEATURES_DEFAULT', {}):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            flag = FeatureFlag.objects.get(key=key)
        except FeatureFlag.DoesNotExist:
            flag = FeatureFlag.objects.create(
                key=key, enabled=bool(settings.FEATURES_DEFAULT.get(key, False)),
            )

        serializer = FeatureFlagUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = snapshot(flag)
        flag.enabled = serializer.validated_data['enabled']
        flag.updated_by = request.user
        flag.save()
        log_action('update', obj=flag, before=before, actor=request.user, request=request)
        return Response(FeatureFlagSerializer(flag).data)
