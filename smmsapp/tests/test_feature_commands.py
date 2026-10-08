from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from smmsapp.models import FeatureFlag
from smmsapp.tasks import check_balance_thresholds

FLAGS = {
    'ANALYTICS': False, 'INSIGHTS': False, 'LEDGER_UI': False,
    'PAYMENTS': False, 'MENU': False, 'PREORDERS': False,
    'SPONSORSHIP': False, 'INTEGRATIONS': False, 'STOCK': False,
    'PARENT_LIMITS': False, 'NFC_SCAN': False,
}


@override_settings(FEATURES_DEFAULT=FLAGS)
class FeatureCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        for key, enabled in FLAGS.items():
            FeatureFlag.objects.update_or_create(key=key, defaults={'enabled': enabled})

    def test_set_feature_turns_flag_on_and_off_and_rejects_typos(self):
        call_command('set_feature', 'ANALYTICS', '--on')
        self.assertTrue(FeatureFlag.objects.get(key='ANALYTICS').enabled)
        call_command('set_feature', 'ANALYTICS', '--off')
        self.assertFalse(FeatureFlag.objects.get(key='ANALYTICS').enabled)
        with self.assertRaises(CommandError):
            call_command('set_feature', 'ANALYTIC', '--on')

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
