"""예매일 확인·추출 및 예매 상태 판정 (PRD F6, 4.1).

원칙: 확인된 경우에만 일자를 출력한다. 모호하면 미확인으로 처리한다.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from core.models import (
    KST,
    STATUS_NOT_REQUIRED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    STATUS_UPCOMING,
    Activity,
)

# 예매 오픈을 알리는 키워드
_OPEN_KW = re.compile(
    r"티켓\s*오픈|예매\s*오픈|예매\s*시작|예매\s*개시|예매\s*일정|예매\s*일시|예매\s*기간"
    r"|예약\s*오픈|예약\s*시작|사전\s*예약\s*기간|사전\s*예약\s*시작"
)
# 날짜(+선택적 시각) 패턴: 2026.11.12 / 11월 12일 / 11/12(목) 오후 2시 / 14:00
_DATE = re.compile(
    r"(?:(?P<y>20\d{2})\s*[.\-/년]\s*)?"
    r"(?P<m>1[0-2]|0?[1-9])\s*[.\-/월]\s*(?P<d>3[01]|[12]\d|0?[1-9])\s*일?"
    r"(?:\s*\([^)]{1,3}\))?"
    r"(?:\s*(?P<ampm>오전|오후|AM|PM|am|pm)?\s*(?P<h>2[0-3]|[01]?\d)\s*"
    r"(?::\s*(?P<mi>[0-5]\d)|시(?:\s*(?P<mi2>[0-5]?\d)\s*분)?))?"
)
_KW_WINDOW = 40      # 키워드 뒤 탐색 범위(문자)
# 키워드와 날짜 사이에는 구분자(':' 등)나 '일시/일자/안내' 정도만 허용
# → "예매 시작 전 공지 확인, 공연 12월 5일" 처럼 다른 문장의 날짜를 잡지 않도록
_KW_GAP = re.compile(r"\s*(?:일시|일자|날짜|안내|일정|시간)?\s*[:：\-–=]?\s*")
# 날짜 바로 뒤에 붙으면 예매 '마감'을 뜻하는 표현
_END_AFTER = re.compile(r"\s*(?:\([^)]{1,3}\))?\s*(?:[0-2]?\d\s*[:시]\s*\d{0,2}\s*분?)?\s*(?:까지|마감|종료)")

# 예매 불필요 / 필요 표현
_NOT_REQUIRED = re.compile(
    r"(?:예약|예매)\s*(?:없이|불필요)|사전\s*(?:예약|예매)\s*(?:불필요|없음|없이)"
    r"|별도\s*(?:예약|예매)\s*(?:없음|불필요|없이)|현장\s*(?:입장|관람)|자유\s*관람|자유롭게\s*관람"
)
_REQUIRED = re.compile(
    r"(?:예약|예매)(?!\s*(?:불필요|없이|없음))|사전\s*신청"
)


def _resolve_year(month: int, day: int, year: str | None, ref: date | None) -> int | None:
    """연도가 없으면 행사 시작일과 가장 가까운 연도로 특정. 특정 불가하면 None."""
    if year:
        return int(year)
    if ref is None:
        return None
    best: tuple[int, int] | None = None
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            gap = abs((date(y, month, day) - ref).days)
        except ValueError:
            continue
        if best is None or gap < best[0]:
            best = (gap, y)
    if best is None or best[0] > 200:
        return None
    return best[1]


def extract_booking_open(text: str, event_start: date | None) -> tuple[datetime | None, bool]:
    """텍스트에서 예매 오픈 일시 추출. 후보가 2개 이상으로 갈리면 (None, False)."""
    if not text:
        return None, False

    found: dict[date, set[tuple[int, int]]] = {}
    for kw in _OPEN_KW.finditer(text):
        window = text[kw.end(): kw.end() + _KW_WINDOW]
        m = _DATE.search(window)
        if not m or not _KW_GAP.fullmatch(window[: m.start()]):
            continue  # 키워드와 날짜 사이에 다른 말이 끼어 있음 (예: '~', '전 공지')
        if _END_AFTER.match(window[m.end():]):
            continue  # '11.30까지' 같은 마감일
        month, day = int(m.group("m")), int(m.group("d"))
        year = _resolve_year(month, day, m.group("y"), event_start)
        if year is None:
            continue
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        times = found.setdefault(d, set())
        if m.group("h") is not None:
            hour = int(m.group("h"))
            ampm = (m.group("ampm") or "").lower()
            if ampm in ("오후", "pm") and hour < 12:
                hour += 12
            elif ampm in ("오전", "am") and hour == 12:
                hour = 0
            minute = int(m.group("mi") or m.group("mi2") or 0)
            times.add((hour, minute))

    if len(found) != 1:
        return None, False
    d, times = next(iter(found.items()))
    if len(times) > 1:
        return None, False
    if times:
        h, mi = next(iter(times))
        return datetime(d.year, d.month, d.day, h, mi, tzinfo=KST), True
    return datetime(d.year, d.month, d.day, tzinfo=KST), False


def detect_booking_required(text: str) -> bool | None:
    """True=예약 필요 표현 있음, False=불필요가 명시됨, None=불명확."""
    if not text:
        return None
    if _NOT_REQUIRED.search(text):
        # '예약 없이' 등과 별개로 예약이 필요하다는 표현이 함께 있으면 불명확 처리
        stripped = _NOT_REQUIRED.sub(" ", text)
        return None if _REQUIRED.search(stripped) else False
    if _REQUIRED.search(text):
        return True
    return None


def booking_status(open_at: datetime | None, time_known: bool,
                   required: bool | None, now: datetime) -> str:
    if open_at is not None:
        if time_known:
            return STATUS_UPCOMING if now < open_at else STATUS_OPEN
        return STATUS_UPCOMING if now.date() <= open_at.date() else STATUS_OPEN
    if required is False:
        return STATUS_NOT_REQUIRED
    return STATUS_UNKNOWN


def annotate_booking(act: Activity, now: datetime) -> Activity:
    """예매일 확인 순서: ① API 필드(소스에서 채움) ② 텍스트 추출 → 이후 불필요 판정."""
    if act.booking_open_at is None:
        dt, time_known = extract_booking_open(act.description, act.start_date)
        if dt is not None:
            act.booking_open_at, act.booking_time_known, act.booking_source = dt, time_known, "text"
    if act.booking_open_at is None and act.booking_required is None:
        act.booking_required = detect_booking_required(act.description)
    act.booking_status = booking_status(
        act.booking_open_at, act.booking_time_known, act.booking_required, now
    )
    return act


_WEEKDAYS = "월화수목금토일"


def format_open_at(open_at: datetime, time_known: bool) -> str:
    s = f"{open_at.month}/{open_at.day}({_WEEKDAYS[open_at.weekday()]})"
    return f"{s} {open_at:%H:%M}" if time_known else s


def d_day_label(open_at: datetime, today: date) -> str:
    days = (open_at.date() - today).days
    if days == 0:
        return "D-day"
    return f"D-{days}" if days > 0 else f"D+{-days}"
