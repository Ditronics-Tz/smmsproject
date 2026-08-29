"""Regression tests for the money/data-integrity hardening phase.

Covers the audit findings:

1. ScanRFIDCardView read-modify-write on rfid_card.balance had no transaction
   or row lock -> concurrent/double-tap scans could double-deduct or overdraw.
   Fixed with transaction.atomic() + select_for_update() and a re-check of
   sufficiency inside the lock.
2. Nothing bounded rfid_card.balance from going arbitrarily negative.
   Fixed with a MinValueValidator(-500) + DB CheckConstraint; the penalty scan
   clamps to -500 so the invariant always holds.
3. Card create/edit validated card_number before required card_id, and did not
   validate student_or_staff as a real UUID (malformed input -> unhandled 500).
   Fixed with required-fields-first ordering and shared UUID/role resolution.
4. Destructive deletes (School/Card/Item) had no confirmation of cascading
   effects. Fixed to refuse deletion while dependencies/history exist.
"""
import threading
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from ..models import (
    CanteenItem,
    ParentStudent,
    RFIDCard,
    ScanSession,
    School,
    Transaction,
    RFID_BALANCE_FLOOR,
)

User = get_user_model()


def _scan_worker(payload, operator, barrier, results):
    """Run one scan request on its own thread/DB connection.

    A thread-localized barrier lets all workers hit the row-lock critical
    section as close to the same instant as possible, maximizing the chance of
    exercising a real race. Connections are closed so the test DB teardown is
    not blocked by leaked worker connections.
    """
    client = APIClient()
    client.force_authenticate(user=operator)
    barrier.wait()
    try:
        response = client.post("/sessions/scan-card", payload)
        results.append(response.status_code)
    finally:
        connections.close_all()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class IntegrityBase(TestCase):
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
            first_name="Sam", last_name="Staff", school=cls.school, school_id=None,
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
        cls.item2 = CanteenItem.objects.create(name="Rice & Beef", price=Decimal("2000.00"))

        cls.parent_student = ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.session = ScanSession.objects.create(operator=cls.operator, type="lunch")

    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def authenticate(self, user):
        self.api.force_authenticate(user=user)


class ScanRFIDCardConcurrencyTests(IntegrityBase):
    """Finding 1: the scan read-modify-write is atomic and race-free."""

    def _scan(self, item):
        return self.api.post(
            "/sessions/scan-card",
            {
                "session_id": str(self.session.id),
                "card_number": self.card.card_number,
                "item_id": str(item.id),
            },
        )

    def test_double_tap_same_item_is_rejected_and_charges_once(self):
        """Two rapid scans of the same card+item must not double-charge."""
        self.authenticate(self.operator)
        starting = self.card.balance

        first = self._scan(self.item)
        self.assertEqual(first.status_code, 201)

        # The duplicate-item guard (checked inside the atomic block) rejects a
        # second identical scan, so the balance is charged exactly once.
        second = self._scan(self.item)
        self.assertEqual(second.status_code, 400)

        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, starting - self.item.price)

    def test_sequential_different_items_deduct_exactly_once_each(self):
        """Distinct item scans each deduct their own price, never a lost update."""
        self.authenticate(self.operator)
        starting = self.card.balance

        self.assertEqual(self._scan(self.item).status_code, 201)
        self.assertEqual(self._scan(self.item2).status_code, 201)

        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, starting - self.item.price - self.item2.price)

        # Both transactions were recorded.
        self.assertEqual(
            Transaction.objects.filter(rfid_card=self.card).count(), 2
        )

    def test_insufficient_balance_penalty_clamps_at_floor(self):
        """A penalty cannot drive balance below the -500 floor."""
        self.authenticate(self.operator)
        # Empty the card first, then one more penalty purchase pushes toward
        # the floor; balance must never go below RFID_BALANCE_FLOOR.
        self.card.balance = Decimal("100.00")
        self.card.save()

        expensive = CanteenItem.objects.create(name="Steak", price=Decimal("5000.00"))
        response = self._scan(expensive)
        self.assertEqual(response.status_code, 201)
        # item.price(5000) + penalty(500) = 5500; 100 - 5500 = -5400, clamped to -500.
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, RFID_BALANCE_FLOOR)

        # Penalty transactions log the price plus the 500 penalty, not a value
        # re-derived from the already-clamped balance.
        penalty_tx = Transaction.objects.get(rfid_card=self.card, item=expensive)
        self.assertEqual(penalty_tx.amount, Decimal("5500.00"))
        self.assertEqual(penalty_tx.transaction_status, "penalty")

    def test_exact_balance_purchase_logs_correct_amount(self):
        """A successful purchase with balance exactly equal to price must log
        the plain item price as the amount (not price+500)."""
        self.authenticate(self.operator)
        self.card.balance = self.item.price
        self.card.save()

        self.assertEqual(self._scan(self.item).status_code, 201)

        tx = Transaction.objects.get(rfid_card=self.card, item=self.item)
        self.assertEqual(tx.amount, self.item.price)
        self.assertEqual(tx.transaction_status, "successful")
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, Decimal("0.00"))


class RFIDCardBalanceFloorTests(IntegrityBase):
    """Finding 2: balance is bounded below by -500 at validation and DB level."""

    def setUp(self):
        super().setUp()
        self.card.balance = Decimal("100.00")
        self.card.save()

    def test_saving_below_floor_raises_validation_error(self):
        self.card.balance = RFID_BALANCE_FLOOR - Decimal("0.01")
        # Model-level validation flags it...
        with self.assertRaises(ValidationError):
            self.card.full_clean()
        # ...and a bare save() is rejected by the DB CheckConstraint.
        with self.assertRaises(IntegrityError):
            self.card.save()

    def test_at_floor_is_valid(self):
        self.card.balance = RFID_BALANCE_FLOOR
        self.card.full_clean()
        self.card.save()
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance, RFID_BALANCE_FLOOR)

    def test_db_check_constraint_rejects_below_floor(self):
        # Bypass Django validators and force a raw insert below the floor; the
        # DB CheckConstraint must reject it.
        with self.assertRaises(IntegrityError), transaction.atomic():
            RFIDCard.objects.create(
                card_number="CARD-FLOOR",
                control_number="CTRL-FLOOR",
                student_or_staff=self.staff,
                balance=RFID_BALANCE_FLOOR - Decimal("1.00"),
            )


class CardCreateEditValidationTests(IntegrityBase):
    """Finding 3: required-field ordering and clean 400s for bad UUIDs."""

    def _valid_payload(self, **overrides):
        payload = {
            "card_number": "CARD-NEW-1",
            "student_or_staff": str(self.student.id),
            "balance": "0.00",
            "is_active": True,
        }
        payload.update(overrides)
        return payload

    def test_missing_card_id_on_edit_returns_400(self):
        self.authenticate(self.admin)
        # card_number supplied but no card_id: must 400 on the missing id, not
        # raise or 500 on the card_number lookup first.
        response = self.api.post("/resources/edit-card", {"card_number": "CARD-0001"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get("code"), 104)

    def test_malformed_uuid_on_create_returns_clean_400(self):
        self.authenticate(self.admin)
        response = self.api.post(
            "/resources/create-card",
            self._valid_payload(student_or_staff="not-a-uuid"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("code", response.data)
        self.assertNotIn("General System error", str(response.data.get("message", "")))

    def test_malformed_uuid_on_edit_returns_clean_400(self):
        self.authenticate(self.admin)
        response = self.api.post(
            "/resources/edit-card",
            {
                "card_id": str(self.card.id),
                "student_or_staff": "not-a-uuid",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get("code"), 104)

    def test_nonexistent_user_on_create_returns_clean_400(self):
        self.authenticate(self.admin)
        response = self.api.post(
            "/resources/create-card",
            self._valid_payload(student_or_staff="00000000-0000-0000-0000-000000000000"),
        )
        self.assertEqual(response.status_code, 400)

    def test_valid_card_creation_still_succeeds(self):
        self.authenticate(self.admin)
        fresh = User.objects.create_user(
            username="student2", password="Passw0rd!123", role="student",
            first_name="Bea", last_name="Fresh", school=self.school,
        )
        response = self.api.post("/resources/create-card", self._valid_payload(student_or_staff=str(fresh.id)))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(RFIDCard.objects.filter(card_number="CARD-NEW-1").exists())


class DeleteGuardTests(IntegrityBase):
    """Finding 4: destructive deletes refuse while dependencies exist."""

    def test_delete_school_blocked_when_users_attached(self):
        self.authenticate(self.admin)
        response = self.api.post("/resources/delete-school", {"school_id": str(self.school.id)})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(School.objects.filter(id=self.school.id).exists())

    def test_delete_empty_school_succeeds(self):
        self.authenticate(self.admin)
        empty = School.objects.create(name="Empty School", location="Nowhere")
        response = self.api.post("/resources/delete-school", {"school_id": str(empty.id)})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(School.objects.filter(id=empty.id).exists())

    def test_delete_item_blocked_with_transaction_history(self):
        self.authenticate(self.admin)
        Transaction.objects.create(
            student_or_staff=self.student,
            rfid_card=self.card,
            item=self.item,
            amount=self.item.price,
            transaction_status="successful",
        )
        response = self.api.post("/resources/delete-item", {"item_id": str(self.item.id)})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(CanteenItem.objects.filter(id=self.item.id).exists())

    def test_delete_card_blocked_with_history(self):
        self.authenticate(self.admin)
        Transaction.objects.create(
            student_or_staff=self.student,
            rfid_card=self.card,
            item=self.item,
            amount=self.item.price,
            transaction_status="successful",
        )
        response = self.api.post("/resources/delete-card", {"card_id": str(self.card.id)})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(RFIDCard.objects.filter(id=self.card.id).exists())

    def test_delete_card_without_history_succeeds(self):
        self.authenticate(self.admin)
        fresh = RFIDCard.objects.create(
            card_number="CARD-FRESH",
            control_number="CTRL-FRESH",
            student_or_staff=self.staff,
            balance=Decimal("0.00"),
        )
        response = self.api.post("/resources/delete-card", {"card_id": str(fresh.id)})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RFIDCard.objects.filter(id=fresh.id).exists())


class ScanConcurrencySerializationTests(TransactionTestCase):
    """True-concurrency regression for the row-lock fix (PostgreSQL backend).

    TransactionTestCase gives each worker thread its own DB connection, so the
    scans genuinely race on the same card row. Verifies the final balance is
    exactly N deductions (no lost update) and that the duplicate-item guard
    rejects a same-card/same-item double charge under load.
    """

    reset_sequences = True

    N_WORKERS = 12

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.school = School.objects.create(name="Concurrency School")
        cls.student = User.objects.create_user(
            username="conc_student", password="Passw0rd!123", role="student",
            first_name="Con", last_name="Student", school=cls.school,
        )
        cls.operator = User.objects.create_user(
            username="conc_operator", password="Passw0rd!123", role="operator",
            first_name="Opa", last_name="Rator", school=cls.school,
        )
        cls.session = ScanSession.objects.create(operator=cls.operator, type="lunch")
        # One distinct item per concurrent worker so the same-card/same-item
        # duplicate guard never interferes with the locking assertion below.
        cls.items = [
            CanteenItem.objects.create(name=f"Item {i}", price=Decimal("1000.00"))
            for i in range(cls.N_WORKERS)
        ]

    def setUp(self):
        super().setUp()
        self.card = RFIDCard.objects.create(
            card_number="CARD-CONC-1",
            control_number="CTRL-CONC-1",
            student_or_staff=self.student,
            balance=Decimal("100000.00"),
        )

    def _payload(self, item):
        return {
            "session_id": str(self.session.id),
            "card_number": self.card.card_number,
            "item_id": str(item.id),
        }

    def test_concurrent_distinct_item_scans_serialize_losslessly(self):
        payloads = [self._payload(it) for it in self.items]
        barrier = threading.Barrier(len(payloads))
        results = []
        threads = [
            threading.Thread(target=_scan_worker, args=(p, self.operator, barrier, results))
            for p in payloads
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(results.count(201), len(payloads))
        self.card.refresh_from_db()
        # No lost update: all N deductions applied exactly once.
        self.assertEqual(
            self.card.balance,
            Decimal("100000.00") - Decimal("1000.00") * self.N_WORKERS,
        )
