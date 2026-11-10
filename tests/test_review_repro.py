"""4단계 검토에서 발견한 문제의 재현 테스트.

수정 전에는 실패해야 하며, 수정 후 통과해야 한다.
"""
from datetime import date

from core.booking import extract_booking_open
from core.filters import region_match, within_budget
from core.models import Activity
from core.price_parser import parse_price
from core.recommender import is_excluded, load_themes, parse_min_age

KIDS = load_themes()["kids"]


def _act(**kw):
    return Activity(id="x", source="t", title=kw.pop("title", "t"), category="c", **kw)


# [높음] 예매 '기간'의 종료일을 예매 오픈일로 잘못 추출
def test_booking_period_end_is_not_open_date():
    assert extract_booking_open("예매 기간: ~ 2026.11.30 까지", None) == (None, False)


# [높음] 예매 키워드 뒤에 나오는 공연일을 예매 오픈일로 잘못 추출
def test_event_date_after_keyword_is_not_open_date():
    text = "예매 시작 전 공지 확인, 공연 12월 5일"
    assert extract_booking_open(text, date(2026, 12, 5)) == (None, False)


# [높음] 일부 대상만 무료(영유아 등)인 유료 행사가 '무료만 보기'에 노출
def test_partial_free_is_not_free_only():
    pmin, pmax = parse_price("성인 12,000원 / 청소년 10,000원 - 36개월 미만 : 무료")
    act = _act(price_min=pmin, price_max=pmax)
    assert not within_budget(act, 0, 1, True, free_only=True, include_unknown=False)


# [높음] 일부 무료 때문에 최저가 0원으로 잡혀 예산 필터를 그대로 통과
def test_partial_free_does_not_bypass_budget():
    pmin, pmax = parse_price("성인 50,000원 / 미취학 아동 무료")
    act = _act(price_min=pmin, price_max=pmax)
    assert not within_budget(act, 10_000, 1, True, free_only=False, include_unknown=False)


# [중간] '19세 미만 보호자 동반' 같은 문구 때문에 아이 테마에서 제외됨
def test_kids_not_excluded_by_under_19_phrase():
    act = _act(title="가족 체험전", description="만 19세 미만은 보호자 동반 필수")
    assert not is_excluded(act, KIDS, 7)


# [중간] 부분 문자열 매칭으로 '북클럽'이 '클럽' 제외어에 걸림
def test_kids_not_excluded_by_bookclub():
    assert not is_excluded(_act(title="어린이 그림책 북클럽"), KIDS, 7)


# [중간] 이용대상 '성인, 어린이'를 최소 19세로 해석해 아이 테마에서 제외
def test_target_adult_and_child_is_not_19():
    assert parse_min_age("성인, 어린이") != 19
    assert not is_excluded(_act(target="성인, 어린이"), KIDS, 7)


# [중간] '19세 미만'(상한)을 최소 관람연령 19세로 해석
def test_under_19_is_not_min_age_19():
    assert parse_min_age("19세 미만 관람 가능") != 19


# [중간] '광주' 선택 시 경기도 광주시 행사가 섞임
def test_gwangju_metro_excludes_gyeonggi_gwangju():
    act = _act(region="경기도", address="경기도 광주시 퇴촌면")
    assert not region_match(act, "광주")


# [낮음] '2만5000원' 형식을 5,000원으로 해석
def test_price_mixed_man_and_digits():
    assert parse_price("2만5000원") == (25000, 25000)
