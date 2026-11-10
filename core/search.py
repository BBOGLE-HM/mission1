"""검색 파이프라인.

process(): 정규화된 결과 → 중복 제거 → 지역·기간 필터 → 예매 상태 → 테마 제외 → 예산 → 추천 점수
apply_view(): 저장된 결과에 예매 상태·시/군/구 필터와 정렬을 적용 (API 재호출 없이 즉시 반영)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from core.booking import annotate_booking
from core.filters import district_of, in_period, region_match, within_budget
from core.models import (
    STATUS_NOT_REQUIRED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    STATUS_UPCOMING,
    Activity,
)
from core.recommender import Theme, is_excluded, score

SORT_OPTIONS = ["추천순", "예매 오픈 임박순", "가격 낮은순", "마감 임박순"]
NO_DISTRICT = "주소 미상"


@dataclass
class SearchParams:
    region: str
    start: date
    end: date
    budget: int
    people: int = 1
    per_person: bool = True
    free_only: bool = False
    include_unknown_price: bool = False
    child_age_max: int | None = None


_PREFIX = re.compile(r"^\s*(?:\[[^\]]*\]\s*)+")  # 맨 앞 [기관명] 접두어
_NOISE = re.compile(r"[\s\[\]()<>〈〉《》'\"‘’“”·,.:\-]")


def _norm(title: str) -> str:
    return _NOISE.sub("", _PREFIX.sub("", title)).lower()


def dedupe(acts: list[Activity]) -> list[Activity]:
    """여러 소스에 같은 행사가 있으면 가격 정보가 있는 쪽을 남긴다."""
    best: dict[tuple, Activity] = {}
    for a in acts:
        key = (_norm(a.title), a.start_date)
        cur = best.get(key)
        if cur is None or (cur.price_min is None and a.price_min is not None):
            best[key] = a
    return list(best.values())


def process(acts: list[Activity], p: SearchParams, theme: Theme, now: datetime) -> list[Activity]:
    today = now.date()
    out: list[Activity] = []
    for a in dedupe(acts):
        if not region_match(a, p.region):
            continue
        if not in_period(a, p.start, p.end, today):
            continue
        annotate_booking(a, now)
        if is_excluded(a, theme, p.child_age_max):
            continue
        if not within_budget(a, p.budget, p.people, p.per_person, p.free_only, p.include_unknown_price):
            continue
        a.score, a.reasons = score(a, theme, now, p.budget, p.people, p.per_person, p.child_age_max)
        out.append(a)
    out.sort(key=lambda a: -a.score)
    return out


_STATUS_ORDER = {STATUS_UPCOMING: 0, STATUS_OPEN: 1, STATUS_NOT_REQUIRED: 2, STATUS_UNKNOWN: 3}


def _sort_key(sort: str):
    if sort == "예매 오픈 임박순":
        return lambda a: (_STATUS_ORDER[a.booking_status],
                          a.booking_open_at.timestamp() if a.booking_open_at else 0, -a.score)
    if sort == "가격 낮은순":
        return lambda a: (a.price_min is None, a.price_min or 0, -a.score)
    if sort == "마감 임박순":
        return lambda a: (a.end_date is None, a.end_date or date.max, -a.score)
    return lambda a: -a.score


def apply_view(acts: list[Activity], statuses: list[str] | None = None,
               districts: list[str] | None = None, sort: str = "추천순") -> list[Activity]:
    """statuses/districts 가 None 이면 전체, 빈 리스트면 아무것도 선택하지 않은 것(0건)."""
    out = [a for a in acts if statuses is None or a.booking_status in statuses]
    if districts is not None:
        out = [a for a in out if (district_of(a) or NO_DISTRICT) in districts]
    return sorted(out, key=_sort_key(sort))


def district_options(acts: list[Activity]) -> list[str]:
    found = sorted({district_of(a) or NO_DISTRICT for a in acts})
    if NO_DISTRICT in found:
        found.remove(NO_DISTRICT)
        found.append(NO_DISTRICT)
    return found
