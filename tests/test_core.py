from datetime import date, datetime

import pytest

from core.booking import (
    annotate_booking,
    booking_status,
    detect_booking_required,
    extract_booking_open,
)
from core.filters import in_period, region_match, within_budget
from core.models import (
    KST,
    STATUS_NOT_REQUIRED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    STATUS_UPCOMING,
    Activity,
)
from core.price_parser import parse_price
from core.recommender import is_excluded, load_themes, parse_min_age
from core.search import SearchParams, apply_view, process
from sources import demo

NOW = datetime(2026, 11, 10, 14, 30, tzinfo=KST)


# ── 가격 파싱 ──
@pytest.mark.parametrize("text,expected", [
    ("R석 120,000원, S석 90,000원", (90000, 120000)),
    ("전석 무료", (0, 0)),
    ("성인 5,000원 / 어린이 무료", (5000, 5000)),  # 일부 무료는 최저가에 반영하지 않음 (H2)
    ("1만5천원", (15000, 15000)),
    ("3만원", (30000, 30000)),
    ("만 7세 이상", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


# ── 예매일 추출 ──
def test_extract_full_datetime():
    dt, known = extract_booking_open("티켓오픈: 2026.11.12 14:00 인터파크", None)
    assert dt == datetime(2026, 11, 12, 14, 0, tzinfo=KST) and known


def test_extract_korean_pm_without_year_uses_event_start():
    dt, known = extract_booking_open("예매 오픈 11월 20일(금) 오후 2시", date(2026, 12, 5))
    assert dt == datetime(2026, 11, 20, 14, 0, tzinfo=KST) and known


def test_extract_year_crossing():
    dt, _ = extract_booking_open("티켓 오픈 12월 20일", date(2027, 1, 10))
    assert dt.date() == date(2026, 12, 20)


def test_extract_no_year_no_event_start_is_unknown():
    assert extract_booking_open("티켓오픈 11월 20일", None) == (None, False)


def test_extract_ambiguous_multiple_dates_is_unknown():
    text = "선예매 티켓오픈 2026.11.12 14:00, 일반 예매 오픈 2026.11.14 14:00"
    assert extract_booking_open(text, None) == (None, False)


def test_extract_date_only():
    dt, known = extract_booking_open("예매 시작 2026-11-15", None)
    assert dt.date() == date(2026, 11, 15) and not known


def test_extract_ignores_far_date():
    # 키워드와 날짜가 멀리 떨어져 있으면 예매일로 보지 않음
    text = "예매 오픈 안내는 공식 홈페이지 공지사항을 참고 바랍니다 2026.11.15"
    assert extract_booking_open(text, None) == (None, False)


# ── 예매 필요 여부 ──
@pytest.mark.parametrize("text,expected", [
    ("예약 없이 현장 입장 가능", False),
    ("사전예약 불필요, 자유 관람", False),
    ("별도 예약 없이 이용", False),
    ("사전예약 필수", True),
    ("현장 입장 가능 (온라인 예매 시 할인)", None),
    ("가을 공연", None),
])
def test_detect_booking_required(text, expected):
    assert detect_booking_required(text) is expected


# ── 예매 상태 ──
def test_booking_status_rules():
    future = datetime(2026, 11, 12, 14, tzinfo=KST)
    past = datetime(2026, 11, 1, 10, tzinfo=KST)
    assert booking_status(future, True, None, NOW) == STATUS_UPCOMING
    assert booking_status(past, True, None, NOW) == STATUS_OPEN
    assert booking_status(None, False, False, NOW) == STATUS_NOT_REQUIRED
    assert booking_status(None, False, None, NOW) == STATUS_UNKNOWN
    assert booking_status(None, False, True, NOW) == STATUS_UNKNOWN
    # 오늘 오픈인데 시각 미확인 → 오픈 예정(D-day)
    today_open = datetime(2026, 11, 10, tzinfo=KST)
    assert booking_status(today_open, False, None, NOW) == STATUS_UPCOMING


def test_confirmed_date_has_priority_over_not_required():
    a = Activity(id="x", source="t", title="t", category="c",
                 description="현장 입장 가능. 예매 오픈 2026.11.20 10:00")
    annotate_booking(a, NOW)
    assert a.booking_status == STATUS_UPCOMING


# ── 필터 ──
def _act(**kw):
    return Activity(id="x", source="t", title="t", category="c", **kw)


def test_in_period():
    today = NOW.date()
    s, e = today, date(2026, 11, 24)
    assert not in_period(_act(start_date=date(2026, 11, 1), end_date=date(2026, 11, 9)), s, e, today)
    assert in_period(_act(start_date=date(2026, 11, 1), end_date=date(2026, 11, 30)), s, e, today)
    assert not in_period(_act(start_date=date(2026, 12, 1), end_date=date(2026, 12, 5)), s, e, today)
    assert in_period(_act(), s, e, today)  # 상시


def test_within_budget():
    paid = _act(price_min=30000)
    assert within_budget(paid, 50000, 1, True, False, False)
    assert not within_budget(paid, 50000, 2, False, False, False)  # 총액 60,000
    assert not within_budget(paid, 50000, 1, True, True, False)    # 무료만
    assert within_budget(_act(price_min=0), 0, 1, True, True, False)
    assert not within_budget(_act(), 50000, 1, True, False, False)  # 가격 미확인 숨김
    assert within_budget(_act(), 50000, 1, True, False, True)


def test_region_match():
    assert region_match(_act(region="서울특별시"), "서울")
    assert not region_match(_act(region="부산광역시", address="부산 해운대구"), "서울")
    assert region_match(_act(), "서울")


# ── 테마 ──
def test_parse_min_age():
    assert parse_min_age("만 7세 이상") == 7
    assert parse_min_age("24개월 이상") == 2
    assert parse_min_age("청소년관람불가") == 19
    assert parse_min_age("전체관람가") == 0
    assert parse_min_age(None) is None


def test_kids_excludes_older_rating():
    kids = load_themes()["kids"]
    assert is_excluded(_act(age_rating="만 13세 이상"), kids, 7)
    assert not is_excluded(_act(age_rating="만 3세 이상"), kids, 7)


# ── 파이프라인 (예시 데이터) ──
def test_demo_pipeline_shows_all_four_statuses_and_hides_ended():
    themes = load_themes()
    params = SearchParams(region="서울", start=NOW.date(), end=date(2026, 12, 31),
                          budget=300_000, include_unknown_price=True)
    results = apply_view(process(demo.fetch("서울", NOW.date()), params, themes["solo"], NOW))
    statuses = {a.booking_status for a in results}
    assert statuses == {STATUS_UPCOMING, STATUS_OPEN, STATUS_NOT_REQUIRED, STATUS_UNKNOWN}
    assert all("종료됨" not in a.title for a in results)
