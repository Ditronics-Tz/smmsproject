"""Stable, translatable API error identifiers."""

from enum import Enum

from rest_framework.response import Response


class ErrorCode(str, Enum):
    CARD_NOT_FOUND = 'CARD_NOT_FOUND'
    CARD_INACTIVE = 'CARD_INACTIVE'
    CARD_BLOCKED_STRIKES = 'CARD_BLOCKED_STRIKES'
    SESSION_NOT_ACTIVE = 'SESSION_NOT_ACTIVE'
    NOT_SESSION_OPERATOR = 'NOT_SESSION_OPERATOR'
    DUPLICATE_ITEM_IN_SESSION = 'DUPLICATE_ITEM_IN_SESSION'
    ITEM_INACTIVE = 'ITEM_INACTIVE'
    INSUFFICIENT_BALANCE_PENALTY = 'INSUFFICIENT_BALANCE_PENALTY'
    DEPOSIT_NOT_PENDING = 'DEPOSIT_NOT_PENDING'
    ALREADY_REVERSED = 'ALREADY_REVERSED'
    DUPLICATE_CARD_NUMBER = 'DUPLICATE_CARD_NUMBER'
    DAILY_LIMIT = 'DAILY_LIMIT'
    ITEM_BLOCKED = 'ITEM_BLOCKED'


DEFAULT_DETAILS = {
    ErrorCode.CARD_NOT_FOUND: 'The card was not found.',
    ErrorCode.CARD_INACTIVE: 'The card is inactive.',
    ErrorCode.CARD_BLOCKED_STRIKES: 'The card is blocked after reaching the strike limit.',
    ErrorCode.SESSION_NOT_ACTIVE: 'The scan session is not active.',
    ErrorCode.NOT_SESSION_OPERATOR: 'Only the session operator can perform this action.',
    ErrorCode.DUPLICATE_ITEM_IN_SESSION: 'This item was already scanned in this session.',
    ErrorCode.ITEM_INACTIVE: 'The canteen item is inactive or unavailable.',
    ErrorCode.INSUFFICIENT_BALANCE_PENALTY: 'The meal was served with an insufficient-balance penalty.',
    ErrorCode.DEPOSIT_NOT_PENDING: 'The deposit is no longer pending.',
    ErrorCode.ALREADY_REVERSED: 'The transaction has already been reversed.',
    ErrorCode.DUPLICATE_CARD_NUMBER: 'The card number is already in use.',
    ErrorCode.DAILY_LIMIT: 'This purchase would exceed the student\'s daily spending limit.',
    ErrorCode.ITEM_BLOCKED: 'This item is blocked by the student\'s parent.',
}


def error_payload(code: ErrorCode, detail: str | None = None) -> dict[str, str]:
    """Build the contract response shape without coupling callers to wording."""
    return {'detail': detail or DEFAULT_DETAILS[code], 'code': code.value}


def error_response(code: ErrorCode, http_status: int, detail: str | None = None) -> Response:
    """Return a stable error payload while preserving the endpoint's status."""
    return Response(error_payload(code, detail), status=http_status)
