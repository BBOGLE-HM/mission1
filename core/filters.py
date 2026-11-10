"""날짜·예산·지역 필터 (PRD F1, F3, F4)."""
from __future__ import annotations

from datetime import date

from core.models import Activity
from core.regions import REGIONS


def in_period(act: Activity, start: date, end: date, today: date) -> bool:
    """종료된 항목 제외 + 검색 기간과 겹치는 항목만. 날짜 정보가 없으면(상시) 포함."""
    if act.end_date and act.end_date < today:
        return False
    if act.start_date and act.start_date > end:
        return False
    if act.end_date and act.end_date < start:
        return False
    return True


def within_budget(act: Activity, budget: int, people: int, per_person: bool,
                  free_only: bool, include_unknown: bool) -> bool:
    """price_min 은 '유료 최저가'(일부 무료 제외)이므로 0 이면 전체 무료를 뜻한다."""
    if act.price_min is None:
        return include_unknown and not free_only
    if free_only:
        return act.price_min == 0
    return cost_of(act, people, per_person) <= budget


def cost_of(act: Activity, people: int, per_person: bool) -> int:
    price = act.price_min or 0
    return price if per_person else price * max(people, 1)


def region_match(act: Activity, region: str) -> bool:
    """시/도 이름이 지역 정보(없으면 주소)의 '첫 단어'와 일치하는지 확인. 정보가 없으면 통과.

    첫 단어만 비교해서 '경기도 광주시'가 '광주(광역시)'로 잡히는 일을 막는다.
    """
    info = REGIONS.get(region)
    if not info:
        return True
    source = (act.region or "").strip() or (act.address or "").strip()
    if not source:
        return True
    first = source.split()[0]
    return any(first.startswith(alias) for alias in info["aliases"])


def district_of(act: Activity) -> str | None:
    """주소에서 시/군/구 추출 (예: '서울 마포구 ...' → '마포구')."""
    for token in (act.address or "").split()[1:3]:
        if token.endswith(("구", "군", "시")) and len(token) >= 2:
            return token
    return None
