"""4단계 검토 후 추가한 기능·수정 사항 테스트."""
import time
from datetime import date, datetime

from core.booking import extract_booking_open
from core.filters import district_of
from core.hours import is_late_night, is_open_now, parse_range
from core.models import KST, STATUS_OPEN, STATUS_UNKNOWN, Activity
from core.price_parser import has_partial_free
from core.recommender import is_excluded, load_themes
from core.search import NO_DISTRICT, _norm, apply_view, district_options
from sources.base import SourceError, collect_sources, run_parallel, safe_url
from sources.kopis import date_chunks


def _act(**kw):
    return Activity(id=kw.pop("id", "x"), source="t", title=kw.pop("title", "t"), category="c", **kw)


# ── H1: 예매일 추출 회귀 방지 ──
def test_booking_period_start_is_still_extracted():
    dt, _ = extract_booking_open("예매 기간: 2026.11.01 ~ 2026.11.30", None)
    assert dt.date() == date(2026, 11, 1)


def test_booking_until_is_rejected():
    assert extract_booking_open("예매 시작 11월 30일까지 얼리버드", date(2026, 12, 10)) == (None, False)


def test_booking_label_word_between_is_allowed():
    dt, known = extract_booking_open("티켓 오픈 일시 : 2026.11.20 오후 8시", None)
    assert dt == datetime(2026, 11, 20, 20, 0, tzinfo=KST) and known


# ── H2: 일부 무료 표시 ──
def test_has_partial_free():
    assert has_partial_free("성인 5,000원 / 어린이 무료")
    assert not has_partial_free("전석 무료")
    assert not has_partial_free("전석 30,000원")


# ── H3: 마감 시간 ──
def test_run_parallel_respects_deadline():
    started = time.monotonic()
    out = run_parallel(lambda s: (time.sleep(s), s)[1], [0, 3], deadline=0.5, workers=2)
    assert time.monotonic() - started < 1.5
    assert out == [0, None]


def test_collect_sources_reports_timeout_and_error():
    def slow():
        time.sleep(3)
        return [1]

    def broken():
        raise SourceError("API 오류(02): KEY")

    started = time.monotonic()
    acts, status = collect_sources({"ok": lambda: [_act()], "slow": slow, "bad": broken}, deadline=0.5)
    assert time.monotonic() - started < 1.5
    assert len(acts) == 1
    assert status["ok"] == "1건"
    assert "초과" in status["slow"]
    assert "API 오류" in status["bad"]


# ── M1: 심야 운영 제외 ──
def test_kids_exclude_late_night():
    kids = load_themes()["kids"]
    assert is_excluded(_act(open_hours="19:00 ~ 23:30"), kids, 7)
    assert not is_excluded(_act(open_hours="10:00 ~ 18:00"), kids, 7)


# ── M3: 예매 상태 전체 해제 ──
def test_apply_view_empty_status_selection_returns_nothing():
    acts = [_act(booking_status=STATUS_OPEN), _act(booking_status=STATUS_UNKNOWN)]
    assert apply_view(acts, statuses=[]) == []
    assert len(apply_view(acts, statuses=None)) == 2
    assert len(apply_view(acts, statuses=[STATUS_OPEN])) == 1


# ── M6: KOPIS 31일 분할 ──
def test_date_chunks_split_by_31_days():
    chunks = date_chunks(date(2026, 11, 1), date(2027, 1, 15))
    assert chunks[0] == (date(2026, 11, 1), date(2026, 12, 1))
    assert chunks[1][0] == date(2026, 12, 2)
    assert chunks[-1][1] == date(2027, 1, 15)
    assert all((e - s).days <= 30 for s, e in chunks)


# ── L7: 기관명 접두어 중복 ──
def test_norm_strips_org_prefix():
    assert _norm("[쿼드, 연극의 질문들] 서안화차") == _norm("서안화차")


# ── L8: 링크 스킴 ──
def test_safe_url():
    assert safe_url("https://a.com") == "https://a.com"
    assert safe_url("javascript:alert(1)") is None
    assert safe_url(None) is None


# ── PRD F1: 지금 운영 중 ──
def test_is_open_now():
    tue_14 = datetime(2026, 11, 10, 14, 0, tzinfo=KST)  # 화요일
    mon_14 = datetime(2026, 11, 9, 14, 0, tzinfo=KST)   # 월요일
    assert parse_range("10:00 ~ 18:00") == (600, 1080)
    assert is_open_now("10:00 ~ 18:00", tue_14) is True
    assert is_open_now("10:00 ~ 12:00", tue_14) is False
    assert is_open_now("10:00 ~ 18:00 (매주 월요일 휴관)", mon_14) is False
    assert is_open_now("화요일 ~ 금요일(20:00)", tue_14) is None
    assert is_late_night("20:00 ~ 01:00")


# ── PRD F4: 시/군/구 ──
def test_district_filter():
    a = _act(id="a", address="서울 마포구 합정동")
    b = _act(id="b", address="서울특별시 종로구 세종대로")
    c = _act(id="c", address="예술의전당")
    assert district_of(a) == "마포구" and district_of(b) == "종로구" and district_of(c) is None
    assert district_options([a, b, c]) == ["마포구", "종로구", NO_DISTRICT]
    assert apply_view([a, b, c], districts=["마포구"]) == [a]
