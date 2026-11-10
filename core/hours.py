"""운영시간 문자열 해석 (PRD F1 '지금 운영 중', F2 '심야 운영')."""
from __future__ import annotations

import re
from datetime import datetime

_RANGE = re.compile(r"([01]?\d|2[0-4])\s*:\s*([0-5]\d)\s*[~\-–]\s*([01]?\d|2[0-4])\s*:\s*([0-5]\d)")
_WEEKDAYS = "월화수목금토일"


def parse_range(open_hours: str | None) -> tuple[int, int] | None:
    """'10:00 ~ 18:00' → (600, 1080) 분 단위. 범위가 정확히 하나일 때만 인정."""
    if not open_hours:
        return None
    found = _RANGE.findall(open_hours)
    if len(found) != 1:
        return None
    h1, m1, h2, m2 = map(int, found[0])
    return h1 * 60 + m1, h2 * 60 + m2


def is_open_now(open_hours: str | None, now: datetime) -> bool | None:
    """True=운영 중, False=운영 시간 아님/휴무, None=판단 불가."""
    rng = parse_range(open_hours)
    if rng is None:
        return None
    day = _WEEKDAYS[now.weekday()]
    if re.search(rf"{day}요일\s*(?:은\s*)?(?:휴관|휴무|휴장)", open_hours or ""):
        return False
    start, end = rng
    minute = now.hour * 60 + now.minute
    if end <= start:  # 자정을 넘기는 운영
        return minute >= start or minute < end
    return start <= minute < end


def is_late_night(open_hours: str | None) -> bool:
    """밤 9시 이후 시작하거나 밤 11시 이후까지 운영하면 심야로 본다."""
    rng = parse_range(open_hours)
    if rng is None:
        return False
    start, end = rng
    return start >= 21 * 60 or end >= 23 * 60 or end < start
