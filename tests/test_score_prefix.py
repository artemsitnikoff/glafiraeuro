"""Префикс «NNN-» к фамилии: округление, замена существующего префикса."""

import os
import re

os.environ.setdefault("BOT_TOKEN", "test")


def _format_prefixed(score: int, last_name: str) -> str:
    clean = re.sub(r"^(\d{3}-)+", "", last_name)
    return f"{score:03d}-{clean}"


def test_format_prefix_zero_pad():
    assert _format_prefixed(7, "Иванов") == "007-Иванов"


def test_format_prefix_high():
    assert _format_prefixed(99, "Иванов") == "099-Иванов"


def test_format_prefix_overrides_existing():
    assert _format_prefixed(80, "045-Иванов") == "080-Иванов"


def test_format_prefix_strips_doubled():
    assert _format_prefixed(80, "045-012-Иванов") == "080-Иванов"


def test_is_scored_match():
    assert re.match(r"^\d{3}-", "045-Иванов")
    assert not re.match(r"^\d{3}-", "Иванов")
    assert not re.match(r"^\d{3}-", "12-Иванов")
