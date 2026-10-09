from io import StringIO
import importlib
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.db import connection
from django.test import TestCase, override_settings

from smmsapp.models import FeatureFlag
from smmsapp.services.features import is_enabled
from smmsproject.settings import _canonicalize_feature_defaults
from smmsapp.tasks import check_balance_thresholds

FLAGS = {
    'ANALYTICS': False, 'INSIGHTS': False, 'LEDGER_UI': False,
    'PAYMENTS': False, 'MENU': False, 'PREORDER': False,
    'SPONSORSHIP': False, 'INTEGRATIONS': False, 'STOCK': False,
    'PARENT_LIMITS': False, 'NFC_SCAN': False,
}


@override_settings(FEATURES_DEFAULT=FLAGS)
class FeatureCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        for key, enabled in FLAGS.items():
            FeatureFlag.objects.update_or_create(key=key, defaults={'enabled': enabled})

    def test_legacy_environment_key_maps_to_canonical_preorder_flag(self):
        self.assertEqual(_canonicalize_feature_defaults({'PREORDERS': True}), {'PREORDER': True})
        self.assertEqual(
            _canonicalize_feature_defaults({'PREORDERS': True, 'PREORDER': False}),
            {'PREORDER': False},
        )

    def test_set_feature_turns_flag_on_and_off_and_rejects_typos(self):
        call_command('set_feature', 'ANALYTICS', '--on')
        self.assertTrue(FeatureFlag.objects.get(key='ANALYTICS').enabled)
        call_command('set_feature', 'ANALYTICS', '--off')
        self.assertFalse(FeatureFlag.objects.get(key='ANALYTICS').enabled)
        with self.assertRaises(CommandError):
            call_command('set_feature', 'ANALYTIC', '--on')
        with self.assertRaises(CommandError):
            call_command('set_feature', 'PREORDERS', '--on')
        with self.assertRaises(KeyError):
            is_enabled('PREORDERS')

    def test_list_features_reports_effective_and_default_values(self):
        FeatureFlag.objects.filter(key='MENU').update(enabled=True)
        output = StringIO()
        call_command('list_features', stdout=output)
        self.assertIn('MENU\ttrue\tfalse', output.getvalue())
        self.assertIn('ANALYTICS\tfalse\tfalse', output.getvalue())

    def test_apply_profile_sets_each_supported_feature(self):
        call_command('apply_feature_profile', 'basic')
        basic = {row.key for row in FeatureFlag.objects.filter(enabled=True)}
        self.assertEqual(basic, {'MENU', 'PAYMENTS'})

        call_command('apply_feature_profile', 'full')
        self.assertEqual(FeatureFlag.objects.filter(enabled=True).count(), len(FLAGS))
        with self.assertRaises(CommandError):
            call_command('apply_feature_profile', 'custom')

    def test_preorder_alias_migration_preserves_enabled_state_and_removes_alias(self):
        FeatureFlag.objects.update_or_create(key='PREORDER', defaults={'enabled': False})
        FeatureFlag.objects.update_or_create(key='PREORDERS', defaults={'enabled': True})
        migration = importlib.import_module('smmsapp.migrations.0036_canonicalize_preorder_feature_key')

        migration.canonicalize_preorder_key(apps, SimpleNamespace(connection=connection))

        self.assertTrue(FeatureFlag.objects.get(key='PREORDER').enabled)
        self.assertFalse(FeatureFlag.objects.filter(key='PREORDERS').exists())

    def test_balance_threshold_task_skips_when_feature_off_and_runs_when_on(self):
        with patch('smmsapp.services.alerts.sweep_low_balances') as sweep:
            result = check_balance_thresholds.run()
            self.assertIn('Skipped', result)
            sweep.assert_not_called()

            FeatureFlag.objects.filter(key='PARENT_LIMITS').update(enabled=True)
            cache.clear()
            sweep.return_value = 2
            self.assertIn('2 reminder', check_balance_thresholds.run())
            sweep.assert_called_once_with()
