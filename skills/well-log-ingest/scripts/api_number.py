"""US API well number and Canadian DLS UWI validation.

US API / US Well Number (PPDM 2013 standard, formerly API Bulletin D12A):
  SS-CCC-UUUUU[-DD[-EE]]  state(2) county(3) unique(5) [directional sidetrack(2) [event(2)]]
  -> 10, 12, or 14 digits. State codes are the API's own alphabetical numbering, NOT FIPS
  (Texas = 42, but FIPS 48). Onshore 01-51; offshore areas 55, 56, 60, 61.

A classic data-pipeline defect: storing API numbers as integers drops the leading zero of
states 01-09 (e.g. Colorado 05-123-45678 becomes 512345678, 9 digits). This module never
silently re-pads: it reports `leading_zero_lost` and only pads when the caller decides to.

Usage:
    from api_number import check_api
    check_api("05-123-45678-00-00")       # ApiCheck(normalized='05123456780000', status='ok', ...)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VALID_STATES = {f"{i:02d}" for i in range(1, 52)} | {"55", "56", "60", "61"}
DLS = re.compile(r"^[1-9]\d{2}/?\d{2}-?\d{2}-?\d{3}-?\d{2}W\d/?\d{2}$", re.IGNORECASE)
API_ZERO_PAD_OPTIONS = ("pad", "reject")


@dataclass(frozen=True)
class ApiCheck:
    raw: str
    normalized: str | None
    status: str           # ok | leading_zero_lost | invalid_state | bad_length | ca_dls | empty
    kind: str             # us_api | ca_dls | unknown
    note: str = ""


def _digits(raw: str) -> str:
    return re.sub(r"[\s\-./]", "", raw)


def check_api(raw: str | None, zero_pad: str | None = None) -> ApiCheck:
    """Validate one identifier. zero_pad: None (report only), 'pad', or 'reject'."""
    text = (raw or "").strip()
    if not text:
        return ApiCheck(text, None, "empty", "unknown")
    if DLS.match(text.replace(" ", "")):
        return ApiCheck(text, text.upper().replace(" ", ""), "ca_dls", "ca_dls", "Canadian DLS UWI")
    digits = _digits(text)
    if not digits.isdigit():
        return ApiCheck(text, None, "bad_length", "unknown", "non-numeric characters")
    if len(digits) in (9, 11, 13):
        return _leading_zero(text, digits, zero_pad)
    if len(digits) not in (10, 12, 14):
        return ApiCheck(text, None, "bad_length", "unknown", f"{len(digits)} digits; expected 10/12/14")
    if digits[:2] not in VALID_STATES:
        return ApiCheck(text, None, "invalid_state", "us_api", f"state code {digits[:2]} not an API state code")
    return ApiCheck(text, digits.ljust(14, "0"), "ok", "us_api")


def _leading_zero(text: str, digits: str, zero_pad: str | None) -> ApiCheck:
    padded = "0" + digits
    plausible = padded[:2] in VALID_STATES
    note = f"{len(digits)} digits; '0{digits[:1]}' {'is' if plausible else 'is not'} a valid state code"
    if zero_pad == "pad" and plausible:
        return ApiCheck(text, padded.ljust(14, "0"), "ok", "us_api", "leading zero restored: " + note)
    return ApiCheck(text, None, "leading_zero_lost", "us_api", note)


def api_state(normalized: str | None) -> str | None:
    """Two-digit API state code of a normalized US API number."""
    if normalized and normalized.isdigit() and len(normalized) == 14:
        return normalized[:2]
    return None
