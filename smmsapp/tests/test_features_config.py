from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from smmsapp.models import AuditLog, FeatureFlag, School
from smmsapp.services.features import all_flags, is_enabled

User = get_user_model()


@override_settings(FEATURES_DEFAULT={'NEW_MENU': True, 'BETA_REPORTS': False})
class FeatureFlagTests(TestCase):
    def setUp(self):
        cache.clear()
        self.flag = FeatureFlag.objects.create(key='NEW_MENU', enabled=False, description='Menu rollout')

    def test_database_value_overrides_environment_default(self):
        self.assertFalse(is_enabled('NEW_MENU'))
        self.assertFalse(all_flags()['NEW_MENU'])
        self.assertFalse(is_enabled('BETA_REPORTS'))

    def test_unknown_code_key_raises(self):
        with self.assertRaises(KeyError):
            is_enabled('NEW_MNEU')

    def test_model_update_invalidates_cached_values(self):
        self.assertFalse(is_enabled('NEW_MENU'))
        self.flag.enabled = True
        self.flag.save()
        self.assertTrue(is_enabled('NEW_MENU'))

    def test_config_permission_matrix_and_audit(self):
        school = School.objects.create(name='Flag School', location='Dar es Salaam')
        parent = User.objects.create_user(username='flag-parent', password='secret', role='parent', school=school)
        admin = User.objects.create_user(username='flag-admin', password='secret', role='admin', school=school)
        root = User.objects.create_superuser(username='flag-root', password='secret', email='root@example.com')
        client = APIClient()

        self.assertEqual(client.get('/api/v1/config/public').status_code, 200)
        self.assertNotIn('features', client.get('/api/v1/config/public').json())
        self.assertIn(client.get('/api/v1/config/features').status_code, (401, 403))

        client.force_authenticate(parent)
        self.assertEqual(client.get('/api/v1/config/features').status_code, 200)
        self.assertEqual(client.put('/api/v1/config/features/NEW_MENU', {'enabled': True}).status_code, 403)

        client.force_authenticate(admin)
        self.assertEqual(client.put('/api/v1/config/features/NEW_MENU', {'enabled': True}).status_code, 403)

        client.force_authenticate(root)
        response = client.put('/api/v1/config/features/NEW_MENU', {'enabled': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['enabled'])
        self.assertEqual(AuditLog.objects.filter(action='update').count(), 1)
        self.assertEqual(client.put('/api/v1/config/features/UNKNOWN', {'enabled': True}, format='json').status_code, 404)
