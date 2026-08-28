"""Regression tests for the Phase 1 hard-crash fixes.

Each test maps to one of the five crash classes fixed in this phase:

1. CardDetailsView queried a non-existent ``role`` field on RFIDCard
   -> guaranteed FieldError.
2. Student/Parent/Staff/Operator detail views assigned ``serializer_class``
   as a tuple (trailing comma) while extending RetrieveAPIView whose GET
   requires an <pk> URL kwarg the routes never provided.
3. utils.generate_parent_end_of_day_report filtered on ``student`` /
   ``student__in`` although the real field name is ``student_or_staff``.
4. ScannedDataListView searched ``status`` / ``start_at``, fields that
   exist on ScanSession but not on ScannedData.
5. Eight list views called ``request.data.get("search").strip()`` and blew
   up with AttributeError whenever the ``search`` key was omitted.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ..models import (
    CanteenItem,
    Notification,
    ParentStudent,
    RFIDCard,
    ScanSession,
    ScannedData,
    School,
    Transaction,
)
User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class Phase1RegressionBase(TestCase):
    """Shared fixtures for every Phase 1 regression test."""

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
        )
        cls.student = User.objects.create_user(
            username="student1", password="Passw0rd!123", role="student",
            first_name="Asha", last_name="Mzee", school=cls.school,
        )
        cls.staff = User.objects.create_user(
            username="staff1", password="Passw0rd!123", role="staff",
            first_name="Sam", last_name="Staff", school=cls.school,
        )
        cls.operator = User.objects.create_user(
            username="operator1", password="Passw0rd!123", role="operator",
            first_name="Opa", last_name="Rator", school=cls.school,
        )

        cls.card = RFIDCard.objects.create(
            card_number="CARD-0001",
            control_number="CTRL-0001",
            student_or_staff=cls.student,
            balance=Decimal("5000.00"),
        )
        cls.item = CanteenItem.objects.create(name="Chapati & Beans", price=Decimal("1500.00"))

        cls.parent_student = ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.transaction = Transaction.objects.create(
            student_or_staff=cls.student,
            rfid_card=cls.card,
            item=cls.item,
            amount=Decimal("1500.00"),
            transaction_status="successful",
        )
        cls.session = ScanSession.objects.create(operator=cls.operator, type="lunch")
        cls.scan = ScannedData.objects.create(
            session=cls.session,
            student_or_staff=cls.student,
            rfid_card=cls.card,
            item=cls.item,
        )
        cls.notification = Notification.objects.create(
            recipient=cls.parent,
            title="Purchase",
            message="Asha bought Chapati & Beans.",
            type="transaction",
        )

    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def authenticate(self, user):
        self.api.force_authenticate(user=user)


class CardDetailsTests(Phase1RegressionBase):
    """Bug 1: invalid `role='admin'` kwarg on the RFIDCard lookup."""

    def test_admin_can_fetch_card_details(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/card-details", {"card_id": str(self.card.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.card.id))

    def test_missing_card_id_returns_400(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/card-details", {})
        self.assertEqual(response.status_code, 400)

    def test_non_admin_is_forbidden(self):
        self.authenticate(self.operator)
        response = self.api.post("/resources/card-details", {"card_id": str(self.card.id)})
        self.assertEqual(response.status_code, 403)


class UserDetailViewTests(Phase1RegressionBase):
    """Bug 2: tuple serializer_class broke these detail views."""

    def _post_detail(self, url, payload):
        self.authenticate(self.admin)
        return self.api.post(url, payload)

    def test_student_details_returns_student(self):
        response = self._post_detail("/resources/student-details", {"student_id": str(self.student.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.student.id))

    def test_parent_details_returns_parent(self):
        response = self._post_detail("/resources/parent-details", {"parent_id": str(self.parent.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.parent.id))

    def test_staff_details_returns_staff(self):
        response = self._post_detail("/resources/staff-details", {"staff_id": str(self.staff.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.staff.id))

    def test_operator_details_returns_operator(self):
        response = self._post_detail("/resources/operator-details", {"operator_id": str(self.operator.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.operator.id))

    def test_get_method_is_rejected_cleanly(self):
        """GET was never functional on these routes; APIView must answer 405, not crash."""
        self.authenticate(self.admin)
        response = self.api.get("/resources/student-details")
        self.assertEqual(response.status_code, 405)


class ParentEndOfDayReportTests(Phase1RegressionBase):
    """Bug 3: wrong FK lookups in the parent PDF report."""

    def test_report_generates_pdf_bytes(self):
        """The parent PDF report must generate cleanly (was FieldError)."""
        self.authenticate(self.parent)
        response = self.api.get("/dashboard/end-of-day-report")
        self.assertEqual(response.status_code, 200)
        bytes_out = b"".join(response.streaming_content)
        self.assertEqual(bytes_out[:4], b"%PDF")


class ScannedDataListTests(Phase1RegressionBase):
    """Bug 4: search fields that do not exist on ScannedData."""

    def test_search_by_card_number(self):
        self.authenticate(self.admin)
        response = self.api.post(
            "/sessions/scanned-data/",
            {"session_id": str(self.session.id), "search": "CARD"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    def test_missing_session_id_returns_400_without_touching_db(self):
        self.authenticate(self.admin)
        response = self.api.post("/sessions/scanned-data/", {})
        self.assertEqual(response.status_code, 400)

    def test_omitted_search_key_does_not_crash(self):
        self.authenticate(self.admin)
        response = self.api.post("/sessions/scanned-data/", {"session_id": str(self.session.id)})
        self.assertEqual(response.status_code, 200)


class OmittedSearchKeyTests(Phase1RegressionBase):
    """Bug 5: `.get("search").strip()` AttributeError when the key is absent."""

    def test_users_list(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/users-list/", {"role": "student"})
        self.assertEqual(response.status_code, 200)

    def test_inactive_users_list(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/inactive-users-list/", {})
        self.assertEqual(response.status_code, 200)

    def test_school_list(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/school-list/", {})
        self.assertEqual(response.status_code, 200)

    def test_item_list(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/item-list/", {})
        self.assertEqual(response.status_code, 200)

    def test_card_list(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/card-list/", {})
        self.assertEqual(response.status_code, 200)

    def test_all_notifications_list(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/all-notifications/", {})
        self.assertEqual(response.status_code, 200)

    def test_transaction_list_as_admin(self):
        self.authenticate(self.admin)
        response = self.api.post("/sessions/transaction-list/", {})
        self.assertEqual(response.status_code, 200)

    def test_transaction_list_as_parent_scopes_to_children(self):
        self.authenticate(self.parent)
        response = self.api.post("/sessions/transaction-list/", {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)


class LoginFcmTokenTests(TestCase):
    """Login with unknown credentials + fcm_token must not crash on None user."""

    def test_unknown_credentials_with_fcm_token_returns_401(self):
        self.api = APIClient()
        response = self.api.post(
            "/auth/login",
            {"username": "ghost-user", "password": "wrongpass", "fcm_token": "fcm-abc"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("message", response.data)

    def test_valid_login_persists_fcm_token(self):
        user = User.objects.create_user(
            username="fcmuser", password="Passw0rd!123", role="student",
        )
        self.api = APIClient()
        response = self.api.post(
            "/auth/login",
            {"username": "fcmuser", "password": "Passw0rd!123", "fcm_token": "fcm-xyz"},
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.fcm_token, "fcm-xyz")
