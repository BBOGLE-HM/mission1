"""비정형 가격 문자열 → (최저가, 최고가) 파싱.

규칙
- 유료 금액이 하나라도 있으면 최저가 = 유료 금액 중 최솟값 (영유아 무료 등 '일부 무료'는 최저가에 반영하지 않음)
- 유료 금액 없이 '무료'만 있으면 (0, 0)
- 금액 정보가 없으면 (None, None)

예) "R석 120,000원, S석 90,000원" → (90000, 120000)
    "전석 무료" → (0, 0)
    "성인 5,000원 / 어린이 무료" → (5000, 5000)  ※ has_partial_free() 로 '일부 무료' 표시
    "1만5천원" → 15000, "2만5000원" → 25000
"""
from __future__ import annotations

import re

_FREE = re.compile(r"무료|free", re.I)
_MAN = re.compile(r"(\d+)\s*만\s*(?:(\d)\s*천\s*|(\d{1,4})\s*)?원")
_CHEON = re.compile(r"(\d)\s*천\s*원")
_WON = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")
_MAX_REASONABLE = 10_000_000


def _amounts(text: str) -> list[int]:
    amounts: list[int] = []
    rest = text
    for m in _MAN.finditer(rest):
        value = int(m.group(1)) * 10_000
        if m.group(2):
            value += int(m.group(2)) * 1_000
        elif m.group(3):
            value += int(m.group(3))
        amounts.append(value)
    rest = _MAN.sub(" ", rest)
    for m in _CHEON.finditer(rest):
        amounts.append(int(m.group(1)) * 1_000)
    rest = _CHEON.sub(" ", rest)
    for m in _WON.finditer(rest):
        amounts.append(int(m.group(1).replace(",", "")))
    return [a for a in amounts if 0 <= a < _MAX_REASONABLE]


def parse_price(text: str | None) -> tuple[int | None, int | None]:
    if not text or not text.strip():
        return None, None
    amounts = _amounts(text)
    paid = [a for a in amounts if a > 0]
    if paid:
        return min(paid), max(paid)
    if _FREE.search(text) or 0 in amounts:
        return 0, 0
    return None, None


def has_partial_free(text: str | None) -> bool:
    """유료 행사지만 일부 대상(영유아 등)은 무료인 경우."""
    if not text:
        return False
    return bool(_FREE.search(text)) and any(a > 0 for a in _amounts(text))


def format_price(price_min: int | None, price_max: int | None) -> str:
    if price_min is None:
        return "가격 확인 필요"
    if price_max is None or price_max == price_min:
        return "무료" if price_min == 0 else f"{price_min:,}원"
    low = "무료" if price_min == 0 else f"{price_min:,}원"
    return f"{low} ~ {price_max:,}원"
