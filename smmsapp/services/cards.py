import re


_UID_LENGTHS = {8, 14, 20}  # 4, 7, or 10 bytes, represented as hexadecimal.


def normalize_uid(value):
    """Normalize a phone/reader UID to uppercase hexadecimal without separators.

    Byte-order conversion is intentionally not performed until the physical
    USB-vs-phone investigation establishes that it is required.
    """
    if value is None:
        raise ValueError('UID is required')
    normalized = re.sub(r'[:\-\s]', '', str(value)).upper()
    if len(normalized) not in _UID_LENGTHS or not re.fullmatch(r'[0-9A-F]+', normalized):
        raise ValueError('UID must be 4, 7, or 10 bytes of hexadecimal')
    return normalized
