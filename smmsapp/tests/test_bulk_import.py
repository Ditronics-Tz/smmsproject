import io

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ..models import School, CustomUser, RFIDCard, ParentStudent

User = get_user_model()


def _csv_bytes(rows, header=None):
    import csv
    header = header or ['first_name', 'middle_name', 'last_name', 'gender', 'class_room', 'card_number', 'parent_email', 'parent_mobile']
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode('utf-8')


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class BulkImportBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Azania Secondary", location="Dar es Salaam")
        cls.admin = User.objects.create_user(
            username="admin1", password="Passw0rd!123", role="admin", is_staff=True,
            first_name="Ada", last_name="Admin", school=cls.school,
        )
        cls.parent = User.objects.create_user(
            username="parent1", password="Passw0rd!123", role="parent",
            first_name="Papa", last_name="Mzee", school=cls.school,
            email="parent1@example.com", mobile_number="255700000001",
        )

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)


class ImportTemplateTests(BulkImportBase):
    def test_template_endpoint_returns_csv(self):
        response = self.api.get("/imports/template")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'].split(';')[0], 'text/csv')
        self.assertIn(b'first_name', response.content)
        self.assertIn(b'card_number', response.content)


class ImportUploadTests(BulkImportBase):
    def _upload(self, csv_content, **data):
        return self.api.post(
            "/imports/upload",
            {**data, "file": io.BytesIO(csv_content)},
            format="multipart",
        )

    def test_dry_run_reports_valid_rows_without_mutation(self):
        content = _csv_bytes([
            {'first_name': 'Amina', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1001', 'parent_email': 'parent1@example.com', 'parent_mobile': ''},
        ])
        response = self._upload(content, dry_run=True)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body['dry_run'])
        self.assertEqual(body['summary']['total'], 1)
        self.assertEqual(body['summary']['valid'], 1)
        # No mutation on dry run.
        self.assertFalse(CustomUser.objects.filter(role='student').exists())

    def test_report_flags_invalid_rows_precisely(self):
        content = _csv_bytes([
            {'first_name': '', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1001', 'parent_email': '', 'parent_mobile': ''},
            {'first_name': 'Amina', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1002', 'parent_email': '', 'parent_mobile': ''},
        ])
        response = self._upload(content, dry_run=True)
        body = response.json()
        self.assertEqual(body['summary']['total'], 2)
        self.assertEqual(body['summary']['valid'], 1)
        self.assertEqual(body['summary']['errors'], 1)
        invalid = [r for r in body['rows'] if r['status'] == 'error'][0]
        self.assertTrue(any('first_name is required' in e for e in invalid['errors']))

    def test_non_admin_cannot_upload(self):
        from rest_framework.test import APIClient as C
        self.api = C()
        self.api.force_authenticate(user=self.parent)
        content = _csv_bytes([
            {'first_name': 'Amina', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1001', 'parent_email': '', 'parent_mobile': ''},
        ])
        response = self._upload(content, dry_run=True)
        self.assertEqual(response.status_code, 403)

    def test_missing_file_returns_400(self):
        response = self.api.post("/imports/upload", {"dry_run": True}, format="multipart")
        self.assertEqual(response.status_code, 400)


class ImportCommitTests(BulkImportBase):
    def _commit(self, csv_content, mode="best_effort"):
        return self.api.post(
            "/imports/commit",
            {"mode": mode, "file": io.BytesIO(csv_content)},
            format="multipart",
        )

    def test_commit_creates_students_cards_and_parent_links(self):
        content = _csv_bytes([
            {'first_name': 'Amina', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1001', 'parent_email': 'parent1@example.com', 'parent_mobile': ''},
            {'first_name': 'Bakari', 'middle_name': 'Said', 'last_name': 'Hassan', 'gender': 'M', 'class_room': '5B', 'card_number': 'CARD-1002', 'parent_email': '', 'parent_mobile': ''},
        ])
        response = self._commit(content)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['imported_count'], 2)
        self.assertFalse(body['all_or_nothing_aborted'])

        students = CustomUser.objects.filter(role='student')
        self.assertEqual(students.count(), 2)
        self.assertEqual(RFIDCard.objects.count(), 2)

        # Parent link created for the first student.
        amina = students.get(first_name='Amina')
        self.assertTrue(ParentStudent.objects.filter(parent=self.parent, student=amina).exists())

    def test_best_effort_skips_invalid_rows(self):
        content = _csv_bytes([
            {'first_name': '', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1001', 'parent_email': '', 'parent_mobile': ''},
            {'first_name': 'Amina', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1002', 'parent_email': '', 'parent_mobile': ''},
        ])
        response = self._commit(content, mode="best_effort")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['imported_count'], 1)  # only the valid row
        self.assertEqual(CustomUser.objects.filter(role='student').count(), 1)

    def test_all_or_nothing_rejects_batch_on_any_invalid(self):
        content = _csv_bytes([
            {'first_name': '', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1001', 'parent_email': '', 'parent_mobile': ''},
            {'first_name': 'Amina', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1002', 'parent_email': '', 'parent_mobile': ''},
        ])
        response = self._commit(content, mode="all_or_nothing")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['all_or_nothing_aborted'])
        self.assertEqual(body['imported_count'], 0)
        # Nothing imported.
        self.assertFalse(CustomUser.objects.filter(role='student').exists())

    def test_duplicate_card_number_in_file_rejected_by_best_effort(self):
        content = _csv_bytes([
            {'first_name': 'Amina', 'middle_name': '', 'last_name': 'Juma', 'gender': 'F', 'class_room': '5A', 'card_number': 'CARD-1001', 'parent_email': '', 'parent_mobile': ''},
            {'first_name': 'Bakari', 'middle_name': '', 'last_name': 'Hassan', 'gender': 'M', 'class_room': '5B', 'card_number': 'CARD-1001', 'parent_email': '', 'parent_mobile': ''},
        ])
        response = self._commit(content, mode="best_effort")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # First row imports; second is a duplicate card_number error -> skipped.
        self.assertEqual(body['imported_count'], 1)
        self.assertEqual(CustomUser.objects.filter(role='student').count(), 1)
