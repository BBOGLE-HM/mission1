"""테마별 추천 점수 계산 (PRD F2)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from core.booking import d_day_label
from core.filters import cost_of
from core.hours import is_late_night
from core.models import STATUS_UPCOMING, Activity

THEMES_PATH = Path(__file__).with_name("themes.yaml")
SCORING_PATH = Path(__file__).with_name("scoring.yaml")

# 아이 연령대 → 해당 연령대의 최대 나이
AGE_GROUPS: dict[str, int] = {"0~3세": 3, "4~7세": 7, "8~13세": 13}


@dataclass
class Theme:
    key: str
    label: str
    keywords: dict[str, int] = field(default_factory=dict)
    exclude: list[str] = field(default_factory=list)
    penalty: dict[str, int] = field(default_factory=dict)
    kids: bool = False
    exclude_late_night: bool = False


def load_themes(path: Path = THEMES_PATH) -> dict[str, Theme]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        key: Theme(
            key=key,
            label=cfg["label"],
            keywords=cfg.get("keywords") or {},
            exclude=cfg.get("exclude") or [],
            penalty=cfg.get("penalty") or {},
            kids=bool(cfg.get("kids", False)),
            exclude_late_night=bool(cfg.get("exclude_late_night", False)),
        )
        for key, cfg in raw.items()
    }


def load_weights(path: Path = SCORING_PATH) -> dict[str, float]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


WEIGHTS = load_weights()


def parse_min_age(text: str | None) -> int | None:
    """관람등급/이용대상 문자열에서 '최소' 관람 나이 추출. '19세 미만' 같은 상한 표현은 무시."""
    if not text:
        return None
    if re.search(r"청소년\s*관람\s*불가|성인\s*(?:전용|만)", text):
        return 19
    if m := re.search(r"(?:만\s*)?(\d{1,2})\s*개월\s*이상", text):
        return int(m.group(1)) // 12
    if m := re.search(r"(?:만\s*)?(\d{1,2})\s*세\s*이상", text):
        return int(m.group(1))
    if re.search(r"고등학생\s*이상", text):
        return 17
    if re.search(r"중학생\s*이상", text):
        return 14
    if re.search(r"초등학생\s*이상", text):
        return 8
    if re.search(r"전체\s*관람|누구나|제한\s*없|전\s*연령|어린이|유아|아동|가족", text):
        return 0
    if re.fullmatch(r"\s*성인\s*", text):
        return 19
    return None


def _min_age(act: Activity) -> int | None:
    return parse_min_age(act.age_rating) if act.age_rating else parse_min_age(act.target)


def is_excluded(act: Activity, theme: Theme, child_age_max: int | None) -> bool:
    text = act.text_blob
    if any(kw in text for kw in theme.exclude):
        return True
    if theme.exclude_late_night and is_late_night(act.open_hours):
        return True
    if theme.kids and child_age_max is not None:
        min_age = _min_age(act)
        if min_age is not None and min_age > child_age_max:
            return True
    return False


def score(act: Activity, theme: Theme, now: datetime, budget: int,
          people: int, per_person: bool, child_age_max: int | None,
          w: dict[str, float] = WEIGHTS) -> tuple[float, list[str]]:
    """추천 점수 = 테마 적합도 + 날짜 근접도 + 예산 여유도 (+ 예매 임박). 가중치는 scoring.yaml."""
    text = act.text_blob
    today = now.date()
    reasons: list[str] = []
    total = 0.0

    # 1) 테마 적합도
    hits = [kw for kw in theme.keywords if kw in text]
    fit = min(sum(theme.keywords[k] for k in hits), w["theme_fit_cap"])
    pen = sum(v for k, v in theme.penalty.items() if k in text)
    if theme.kids and "아동" in act.tags:
        fit += w["kids_tag_bonus"]
        if "아동" not in hits:
            hits.insert(0, "아동")
    total += fit * w["theme_fit"] - pen * w["penalty"]
    if hits:
        reasons.append(f"{theme.label.split(' ', 1)[-1]} 추천({', '.join(hits[:3])})")
    if theme.kids and child_age_max is not None:
        min_age = _min_age(act)
        if min_age is not None:
            reasons.append("전체 관람" if min_age == 0 else f"{min_age}세 이상 관람")

    # 2) 날짜 근접도
    if act.start_date and act.start_date > today:
        days = (act.start_date - today).days
        total += max(0.0, w["date_max"] - days / w["date_decay_days"])
        reasons.append(f"{days}일 후 시작")
    elif act.start_date or act.end_date:
        total += w["date_max"]
        reasons.append("진행 중")
        if act.end_date and 0 <= (act.end_date - today).days <= 3:
            reasons.append("곧 종료")

    # 3) 예산 여유도
    if act.price_min == 0:
        total += w["free_bonus"]
        reasons.append("무료")
    elif act.price_min is not None:
        cost = cost_of(act, people, per_person)
        if budget > 0:
            total += w["budget_slack"] * max(0.0, (budget - cost) / budget)
        reasons.append(f"{'1인' if per_person else f'{people}인'} {cost:,}원")

    # 4) 예매 오픈 임박
    if act.booking_status == STATUS_UPCOMING and act.booking_open_at:
        days = (act.booking_open_at.date() - today).days
        if days <= w["booking_soon_days"]:
            total += w["booking_soon"]
        reasons.append(f"예매 오픈 {d_day_label(act.booking_open_at, today)}")

    return round(total, 2), reasons
