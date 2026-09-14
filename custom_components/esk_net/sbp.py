"""Validation for the cabinet's SBP QR response."""

import base64
import binascii
from decimal import Decimal, InvalidOperation

from .parser import EskError

MIN_AMOUNT = 10
MAX_AMOUNT = 100000  # Integration UI limit, not a claimed bank limit.


class SbpError(EskError):
    """Invalid amount or QR response."""


def validate_amount(value) -> int:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as err:
        raise SbpError("Enter a whole number of rubles") from err
    if (
        not amount.is_finite()
        or amount != amount.to_integral_value()
        or not MIN_AMOUNT <= amount <= MAX_AMOUNT
    ):
        raise SbpError("Amount must be a whole number from 10 to 100000 RUB")
    return int(amount)


def decode_qr(response: str) -> bytes:
    if len(response) > 2_000_000:
        raise SbpError("QR response is too large")
    try:
        data = base64.b64decode(response.strip(), validate=True)
    except (ValueError, binascii.Error) as err:
        raise SbpError("Cabinet did not return a QR image") from err
    if (
        len(data) < 45
        or not data.startswith(b"\x89PNG\r\n\x1a\n")
        or data[12:16] != b"IHDR"
        or data[-8:-4] != b"IEND"
    ):
        raise SbpError("Cabinet did not return a PNG image")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if not 0 < width <= 4096 or not 0 < height <= 4096:
        raise SbpError("Invalid QR image dimensions")
    return data
