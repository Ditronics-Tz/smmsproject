from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse

from ..permissions.roles import IsAdminOnly
from ..services.importer import (
    StudentImporter, ImportError, build_template_csv,
)
from ..serializers.imports import (
    ImportUploadSerializer, ImportRowReportSerializer,
)

# CSV template content type / disposition
TEMPLATE_CTYPE = 'text/csv'


class ImportTemplateView(APIView):
    """Download a CSV template (header + one sample row) for bulk onboarding."""
    permission_classes = [IsAdminOnly]

    def get(self, request):
        csv_bytes = build_template_csv()
        response = HttpResponse(csv_bytes, content_type=TEMPLATE_CTYPE)
        response['Content-Disposition'] = 'attachment; filename="student_import_template.csv"'
        return response


class ImportUploadView(APIView):
    """Upload a CSV/XLSX file and validate every row.

    Defaults to dry_run=True, so no mutation happens. Returns a row-level
    validation report (valid/warning/error with precise messages). Pass
    ?dry_run=false to validate only (still no commit — use /imports/commit to
    actually import).
    """
    permission_classes = [IsAdminOnly]
    serializer_class = ImportUploadSerializer

    def post(self, request):
        # Structural validation of the request fields.
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        dry_run = serializer.validated_data.get('dry_run', True)

        file_obj = request.FILES.get('file')
        if file_obj is None:
            return Response(
                {'code': 400, 'message': 'file is required (multipart form field "file")'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        importer = StudentImporter(school=request.user.school)
        if importer.school is None:
            return Response(
                {'code': 400, 'message': 'Your admin account must belong to a school to import students.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            rows = importer.parse(file_obj.read(), filename=file_obj.name)
        except ImportError as e:
            return Response({'code': 400, 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if not rows:
            return Response(
                {'code': 400, 'message': 'The file contains no data rows.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report = importer.validate_rows(rows)

        total = len(report)
        valid = sum(1 for r in report if r['status'] == 'valid')
        errors = total - valid
        report_ser = ImportRowReportSerializer(report, many=True).data

        return Response({
            'dry_run': dry_run,
            'mode': serializer.validated_data.get('mode', 'best_effort'),
            'summary': {'total': total, 'valid': valid, 'errors': errors},
            'rows': report_ser,
        }, status=status.HTTP_200_OK)


class ImportCommitView(APIView):
    """Commit a validated batch of student imports.

    Body: mode ('best_effort' | 'all_or_nothing'). Re-validates the file before
    committing so the commit is safe to call independently of /imports/upload.
    """
    permission_classes = [IsAdminOnly]
    serializer_class = ImportUploadSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        mode = serializer.validated_data.get('mode', 'best_effort')

        file_obj = request.FILES.get('file')
        if file_obj is None:
            return Response(
                {'code': 400, 'message': 'file is required (multipart form field "file")'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        importer = StudentImporter(school=request.user.school)
        if importer.school is None:
            return Response(
                {'code': 400, 'message': 'Your admin account must belong to a school to import students.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            rows = importer.parse(file_obj.read(), filename=file_obj.name)
        except ImportError as e:
            return Response({'code': 400, 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if not rows:
            return Response(
                {'code': 400, 'message': 'The file contains no data rows.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report = importer.validate_rows(rows)
        result, report = importer.commit_rows(rows, report, mode=mode)

        report_ser = ImportRowReportSerializer(report, many=True).data

        return Response({
            'message': 'Import committed.' if not result.get('all_or_nothing_aborted')
                        else 'All-or-nothing import rejected: invalid rows present.',
            'mode': mode,
            'all_or_nothing_aborted': result.get('all_or_nothing_aborted', False),
            'imported_count': len(result.get('committed', [])),
            'skipped_rows': result.get('skipped', []),
            'imported': result.get('committed', []),
            'rows': report_ser,
        }, status=status.HTTP_200_OK)
