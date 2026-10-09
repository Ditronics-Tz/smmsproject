from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from smmsapp.models import JournalEntry, JournalLine, LedgerAccount


class ReadOnlyLedgerAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username='ledger-admin-test', password='test-password-123', email='ledger@example.com',
        )

    def test_ledger_models_are_registered_with_read_only_admin(self):
        request = RequestFactory().get('/admin/')
        request.user = self.user

        for model in (LedgerAccount, JournalEntry, JournalLine):
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request))
                self.assertFalse(model_admin.has_delete_permission(request))
                self.assertEqual(
                    set(model_admin.get_readonly_fields(request)),
                    {field.name for field in model._meta.fields},
                )

