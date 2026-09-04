"""Check a rendered PDF the way an applicant tracking system reads it."""

from __future__ import annotations

from cvme.ats.check import STANDARD_SECTIONS, check_pdf

__all__ = ["STANDARD_SECTIONS", "check_pdf"]
