from django.test import SimpleTestCase
from rest_framework import status

from smmsapp.errors import ErrorCode, error_payload, error_response


class StableErrorCodeTests(SimpleTestCase):
    def test_error_payload_uses_contract_shape_and_default_detail(self):
        self.assertEqual(
            error_payload(ErrorCode.CARD_NOT_FOUND),
            {'detail': 'The card was not found.', 'code': 'CARD_NOT_FOUND'},
        )

    def test_custom_detail_does_not_change_stable_code(self):
        self.assertEqual(
            error_payload(ErrorCode.DEPOSIT_NOT_PENDING, 'Already processed.'),
            {'detail': 'Already processed.', 'code': 'DEPOSIT_NOT_PENDING'},
        )

    def test_response_keeps_requested_http_status(self):
        response = error_response(ErrorCode.ALREADY_REVERSED, status.HTTP_409_CONFLICT)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['code'], 'ALREADY_REVERSED')
