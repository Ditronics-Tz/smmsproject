from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework import serializers

from smmsapp.models import School
from smmsapp.serializers.auth import UserCreateSerializer

User = get_user_model()


class AdminSchoolRequirementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Scoped admin school')
        cls.admin = User.objects.create_user(username='school-admin', role='admin', school=cls.school)
        cls.superuser = User.objects.create_superuser(
            username='platform-owner', email='owner@example.com', password='test-pass-123', school=None, role='admin',
        )

    def _serializer(self, actor, data, instance=None):
        return UserCreateSerializer(instance=instance, data=data, partial=instance is not None,
                                    context={'request': type('Request', (), {'user': actor})()})

    def test_create_admin_requires_school(self):
        serializer = self._serializer(self.admin, {
            'role': 'admin', 'username': 'new-admin', 'first_name': 'A', 'last_name': 'B',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('school', serializer.errors)

    def test_only_superuser_can_create_schoolless_platform_superuser(self):
        serializer = self._serializer(self.superuser, {
            'role': 'admin', 'username': 'global-admin', 'first_name': 'A', 'last_name': 'B',
            'is_superuser': True,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        created = serializer.save()
        self.assertTrue(created.is_superuser)
        self.assertIsNone(created.school_id)

    def test_regular_admin_cannot_create_platform_superuser(self):
        serializer = self._serializer(self.admin, {
            'role': 'admin', 'username': 'bad-global-admin', 'first_name': 'A', 'last_name': 'B',
            'is_superuser': True,
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('is_superuser', serializer.errors)

    def test_edit_admin_requires_school(self):
        existing = User.objects.create_user(username='admin-to-edit', role='admin', school=self.school)
        serializer = self._serializer(self.admin, {'school': None}, instance=existing)
        self.assertFalse(serializer.is_valid())
        self.assertIn('school', serializer.errors)

    def test_command_lists_without_modifying_schoolless_admins(self):
        output = StringIO()
        call_command('list_admins_without_school', stdout=output)
        self.assertIn('platform-owner', output.getvalue())
        self.assertIsNone(User.objects.get(pk=self.superuser.pk).school_id)
