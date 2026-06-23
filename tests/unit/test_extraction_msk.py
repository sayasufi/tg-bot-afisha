"""Telegram posts state Moscow local time without an offset — pin that we anchor it to MSK, not UTC."""
from datetime import timezone

from pipeline.llm.extraction_service import LLMExtractionService


def test_naive_time_is_anchored_to_msk():
    out = LLMExtractionService._to_msk_iso("2026-06-23T21:00:00")
    from datetime import datetime

    dt = datetime.fromisoformat(out)
    assert dt.utcoffset().total_seconds() == 3 * 3600          # tagged +03:00
    assert dt.astimezone(timezone.utc).day == 23                # stays 23 Jun (not 24)
    assert dt.astimezone(timezone.utc).hour == 18               # 21:00 МСК == 18:00 UTC


def test_offset_aware_passes_through_untouched():
    from datetime import datetime

    dt = datetime.fromisoformat(LLMExtractionService._to_msk_iso("2026-06-23T21:00:00+00:00"))
    assert dt.utcoffset().total_seconds() == 0                  # explicit UTC kept as-is


def test_blank_stays_blank():
    assert LLMExtractionService._to_msk_iso("") == ""
