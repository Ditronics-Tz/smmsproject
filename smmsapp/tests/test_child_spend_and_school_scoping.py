from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ..models import (
    School, RFIDCard, CanteenItem, Transaction, ScanSession, ParentStudent,
)

User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school_a = School.objects.create(name="School A")
        cls.school_b = School.objects.create(name="School B")

        cls.admin_global = User.objects.create_user(
            username="globaladmin", password="Passw0rd!123", role="admin", is_staff=True,
        )
        cls.admin_a = User.objects.create_user(
            username="admina", password="Passw0rd!123", role="admin", is_staff=True,
            school=cls.school_a,
        )
        cls.admin_b = User.objects.create_user(
            username="adminb", password="Passw0rd!123", role="admin", is_staff=True,
            school=cls.school_b,
        )
        cls.parent_a = User.objects.create_user(
            username="parenta", password="Passw0rd!123", role="parent", school=cls.school_a,
        )
        cls.student_a = User.objects.create_user(
            username="studenta", password="Passw0rd!123", role="student",
            school=cls.school_a, first_name="Asha", last_name="A",
        )
        cls.student_b = User.objects.create_user(
            username="studentb", password="Passw0rd!123", role="student",
            school=cls.school_b, first_name="Bora", last_name="B",
        )
        cls.operator = User.objects.create_user(
            username="op1", password="Passw0rd!123", role="operator", school=cls.school_a,
        )

        cls.card_a = RFIDCard.objects.create(
            card_number="CARD-A", control_number="CTRL-A",
            student_or_staff=cls.student_a, balance=Decimal("5000.00"), is_active=True,
        )
        cls.card_b = RFIDCard.objects.create(
            card_number="CARD-B", control_number="CTRL-B",
            student_or_staff=cls.student_b, balance=Decimal("9000.00"), is_active=True,
        )

        cls.item = CanteenItem.objects.create(name="Chapati", price=Decimal("1500.00"))
        cls.session = ScanSession.objects.create(operator=cls.operator, type="lunch")

        # student A: one successful purchase today + one penalty today
        Transaction.objects.create(
            student_or_staff=cls.student_a, rfid_card=cls.card_a, item=cls.item,
            amount=Decimal("1500.00"), transaction_status="successful", session=cls.session,
        )
        Transaction.objects.create(
            student_or_staff=cls.student_a, rfid_card=cls.card_a, item=cls.item,
            amount=Decimal("2000.00"), transaction_status="penalty", session=cls.session,
        )
        # student B: one purchase in school B
        Transaction.objects.create(
            student_or_staff=cls.student_b, rfid_card=cls.card_b, item=cls.item,
            amount=Decimal("1500.00"), transaction_status="successful", session=cls.session,
        )

        ParentStudent.objects.create(parent=cls.parent_a, student=cls.student_a)


class ChildSpendTests(Base):
    def test_parent_sees_own_child_spend(self):
        api = APIClient()
        api.force_authenticate(user=self.parent_a)
        response = api.post("/dashboard/children-spend", {"period": "week"})
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data["period"], "week")
        self.assertEqual(len(data["children"]), 1)
        child = data["children"][0]
        self.assertEqual(child["child_id"], str(self.student_a.id))
        # total spend = 1500 (successful) + 2000 (penalty) = 3500
        self.assertEqual(Decimal(child["total_spend"]), Decimal("3500.00"))
        self.assertEqual(child["transaction_count"], 2)
        self.assertEqual(Decimal(child["penalty_amount"]), Decimal("2000.00"))
        # one item breakdown entry with quantity 2
        self.assertEqual(len(child["items"]), 1)
        self.assertEqual(child["items"][0]["item_name"], "Chapati")
        self.assertEqual(child["items"][0]["quantity"], 2)

    def test_period_month_includes_todays_transactions(self):
        api = APIClient()
        api.force_authenticate(user=self.parent_a)
        response = api.post("/dashboard/children-spend", {"period": "month"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Decimal(response.data["children"][0]["total_spend"]), Decimal("3500.00")
        )

    def test_parent_cannot_see_other_schools_children(self):
        api = APIClient()
        api.force_authenticate(user=self.parent_a)
        response = api.post("/dashboard/children-spend", {"period": "week"})
        self.assertEqual(len(response.data["children"]), 1)
        self.assertEqual(response.data["children"][0]["child_id"], str(self.student_a.id))

    def test_only_parents_allowed(self):
        api = APIClient()
        api.force_authenticate(user=self.admin_a)
        response = api.post("/dashboard/children-spend", {"period": "week"})
        self.assertEqual(response.status_code, 403)

    def test_invalid_period_rejected(self):
        api = APIClient()
        api.force_authenticate(user=self.parent_a)
        response = api.post("/dashboard/children-spend", {"period": "year"})
        self.assertEqual(response.status_code, 400)


class SchoolScopedReportingTests(Base):
    def _counts(self, user):
        api = APIClient()
        api.force_authenticate(user=user)
        return api.post("/dashboard/counts", {})

    def test_school_admin_counts_scoped_to_own_school(self):
        response = self._counts(self.admin_a)
        self.assertEqual(response.status_code, 200)
        # School A has 1 student, School B has 1 student.
        self.assertEqual(response.data["total_students"], 1)

    def test_global_admin_counts_include_all(self):
        response = self._counts(self.admin_global)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_students"], 2)
        # sum of both cards: 5000 + 9000 = 14000
        self.assertEqual(Decimal(response.data["total_available_balance"]), Decimal("14000.00"))

    def test_school_admin_sales_summary_scoped(self):
        api = APIClient()
        api.force_authenticate(user=self.admin_a)
        response = api.post("/dashboard/sales-summary", {"filter": "month"})
        self.assertEqual(response.status_code, 200)
        # School A transactions: 1500 + 2000 = 3500
        self.assertEqual(Decimal(response.data["total_success_amount"]), Decimal("1500.00"))
        self.assertEqual(Decimal(response.data["total_penalts_amount"]), Decimal("2000.00"))
        self.assertEqual(response.data["total_success"], 1)
        self.assertEqual(response.data["total_penalts"], 1)

    def test_school_admin_sales_trend_scoped(self):
        api = APIClient()
        api.force_authenticate(user=self.admin_b)
        response = api.post("/dashboard/sales-trend")
        self.assertEqual(response.status_code, 200)
        total = sum(Decimal(d["sales_amount"]) for d in response.data)
        # School B only has the 1500 transaction.
        self.assertEqual(total, Decimal("1500.00"))
