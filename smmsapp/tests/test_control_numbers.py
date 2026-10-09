from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from smmsapp.models import ControlNumberCounter, CustomUser, RFIDCard, School
from smmsapp.services.cards import create_card_with_control_number, generate_control_number
from smmsapp.services.importer import StudentImporter


class ControlNumberTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Control number school')

    def test_bulk_import_of_one_thousand_cards_is_unique(self):
        importer = StudentImporter(self.school)
        rows = [
            {'row_number': index + 2, 'data': {
                'first_name': f'Student{index}', 'middle_name': '', 'last_name': 'Import',
                'gender': 'F', 'class_room': 'A', 'card_number': f'IMPORT-{index:04d}',
                'parent_email': '', 'parent_mobile': '',
            }}
            for index in range(1000)
        ]
        report = importer.validate_rows(rows)
        self.assertEqual(sum(row['status'] == 'valid' for row in report), 1000)
        result, _ = importer.commit_rows(rows, report)
        self.assertEqual(len(result['committed']), 1000)
        control_numbers = list(RFIDCard.objects.values_list('control_number', flat=True))
        self.assertEqual(len(control_numbers), 1000)
        self.assertEqual(len(set(control_numbers)), 1000)
        self.assertTrue(all(len(number) == 12 and number[:2] == f'{self.school.number:02d}' for number in control_numbers))
        self.assertEqual(ControlNumberCounter.objects.get(school=self.school).last_value, 1000)

    def test_existing_control_number_collision_retries(self):
        owner = CustomUser.objects.create_user(username='collision-owner', role='student', school=self.school)
        existing = RFIDCard.objects.create(card_number='OLD-CARD', control_number='FORCED-COLLISION', student_or_staff=owner)
        generated = iter([existing.control_number, 'UNIQUE-RETRY'])
        with patch('smmsapp.services.cards.generate_control_number', side_effect=lambda school: next(generated)):
            card = create_card_with_control_number(
                school=self.school, card_number='NEW-CARD', student_or_staff=owner,
            )
        self.assertEqual(card.control_number, 'UNIQUE-RETRY')

    def test_school_number_does_not_wrap_when_capacity_is_exhausted(self):
        School.objects.bulk_create([
            School(name=f'Capacity school {number}', number=number) for number in range(11, 100)
        ])
        with self.assertRaises(ValidationError):
            School.objects.create(name='School beyond two-digit capacity')


class ConcurrentControlNumberTests(TransactionTestCase):
    reset_sequences = True

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_allocations_never_collide(self):
        from concurrent.futures import ThreadPoolExecutor

        school = School.objects.create(name='Concurrent control number school')
        def allocate(_):
            return generate_control_number(School.objects.get(pk=school.pk))

        with ThreadPoolExecutor(max_workers=8) as pool:
            numbers = list(pool.map(allocate, range(32)))
        self.assertEqual(len(set(numbers)), 32)
        self.assertEqual(ControlNumberCounter.objects.get(school=school).last_value, 32)
