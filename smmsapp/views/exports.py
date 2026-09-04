import os
from uuid import uuid4

from django.conf import settings
from django.core import signing
from django.http import FileResponse, Http404
from django.utils.timezone import now
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Notification
from ..serializers.exports import ExportRequestSerializer
from ..services.exporter import (
    ENTITY_BUILDERS, EXPORT_SYNC_MAX_ROWS,
    export_to_csv, export_to_xlsx,
)

EXPORT_SALT = 'smms-export-download'
EXPORT_MAX_AGE = 3600  # seconds


def _storage_dir():
    d = os.path.join(settings.MEDIA_ROOT, 'exports')
    os.makedirs(d, exist_ok=True)
    return d


def _make_token(entity, filename, user_id):
    return signing.dumps(
        {
            'entity': entity,
            'file': filename,
            'uid': str(user_id),
            'exp': now().timestamp() + EXPORT_MAX_AGE,
        },
        salt=EXPORT_SALT,
    )


def _read_token(token):
    try:
        return signing.loads(token, salt=EXPORT_SALT, max_age=EXPORT_MAX_AGE)
    except Exception:
        return None


def _write_export(entity, filename, user, filters):
    queryset_fn, rows_fn, headers = ENTITY_BUILDERS[entity]
    qs = queryset_fn(user, filters)
    rows = rows_fn(qs)
    if filename.endswith('.xlsx'):
        content = export_to_xlsx(rows, headers)
    else:
        content = export_to_csv(rows, headers)

    path = os.path.join(_storage_dir(), filename)
    with open(path, 'wb') as f:
        f.write(content)
    return path, rows


class BaseExportView(APIView):
    permission_classes = [IsAuthenticated]
    entity = None  # set by subclass

    def post(self, request):
        serializer = ExportRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        filters = {
            'from_date': data.get('from_date'),
            'to_date': data.get('to_date'),
            'status': data.get('status'),
            'search': data.get('search'),
            'class_room': data.get('class_room'),
            'active': data.get('active'),
        }
        export_format = data.get('export_format', 'csv')
        async_mode = data.get('async_mode', False)
        extension = 'xlsx' if export_format == 'xlsx' else 'csv'

        queryset_fn, _, _ = ENTITY_BUILDERS[self.entity]
        estimated = queryset_fn(request.user, filters).count()

        if not async_mode and estimated <= EXPORT_SYNC_MAX_ROWS:
            filename = f"{self.entity}-{uuid4().hex}.{extension}"
            path, _ = _write_export(self.entity, filename, request.user, filters)
            with open(path, 'rb') as f:
                content = f.read()
            os.remove(path)
            from django.http import HttpResponse
            response = HttpResponse(content, content_type=(
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                if extension == 'xlsx' else 'text/csv'
            ))
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        # Async path: enqueue generation and return a short-lived signed token.
        filename = f"{self.entity}-{uuid4().hex}.{extension}"
        token = _make_token(self.entity, filename, request.user.id)

        from ..tasks import generate_export_task
        generate_export_task.delay(
            entity=self.entity,
            filename=filename,
            user_id=str(request.user.id),
            filters={
                k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in filters.items()
            },
        )

        Notification.objects.create(
            recipient=request.user,
            title='Export Requested',
            message=f'Your {self.entity} export is being generated. Use the returned token to download it when ready.',
            status='pending',
            type='reminder',
        )

        return Response({
            'code': 202,
            'message': 'Export accepted. Use the download endpoint with the returned token when ready.',
            'token': token,
        }, status=status.HTTP_202_ACCEPTED)


class TransactionExportView(BaseExportView):
    entity = 'transactions'


class StudentExportView(BaseExportView):
    entity = 'students'


class DepositExportView(BaseExportView):
    entity = 'deposits'


class ExportDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        payload = _read_token(token)
        if payload is None:
            raise Http404('Invalid or expired export token')

        if str(request.user.id) != payload.get('uid'):
            raise Http404('Export not authorized for this user')

        filename = payload.get('file')
        path = os.path.join(_storage_dir(), filename)

        if not os.path.exists(path):
            return Response({
                'code': 202,
                'message': 'Export not ready yet. Please retry shortly.',
            }, status=status.HTTP_202_ACCEPTED)

        response = FileResponse(
            open(path, 'rb'),
            content_type=(
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                if filename.endswith('.xlsx') else 'text/csv'
            ),
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        os.remove(path)
        return response
