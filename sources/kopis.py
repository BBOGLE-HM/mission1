"""KOPIS 공연예술통합전산망 API (공연).

목록: /pblprfr?service=KEY&stdate=YYYYMMDD&eddate=YYYYMMDD&cpage=1&rows=N[&signgucode][&kidstate=Y]
      조회 기간은 최대 31일 → 긴 기간은 31일 단위로 나눠 조회
상세: /pblprfr/{mt20id}?service=KEY  → 가격(pcseguidance), 관람연령(prfage), 러닝타임(prfruntime), 예매처(relates)
상세 조회는 마감 시간 안에서만 수행하고, 끝나지 않은 항목은 목록 정보(가격 미확인)로 남긴다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from core.models import Activity
from core.price_parser import parse_price
from core.regions import REGIONS
from sources.base import SourceError, http_get, run_parallel, to_https

BASE = "https://www.kopis.or.kr/openApi/restful"
DETAIL_PAGE = "https://www.kopis.or.kr/por/db/pblprfr/pblprfrView.do?menuId=MNU_00020&mt20Id={id}"
MAX_RANGE_DAYS = 31     # KOPIS 1회 조회 기간 한도
MAX_CHUNKS = 3          # 최대 93일
ROWS = 100              # 1회 목록 건수
DETAIL_DEADLINE = 3.5   # 상세 조회 전체 마감(초)


def _text(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    found = el.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def _date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y.%m.%d").date()
    except ValueError:
        return None


def _get_xml(url: str, params: dict) -> ET.Element:
    resp = http_get(url, params)
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise SourceError("응답 형식 오류") from e
    code = root.findtext(".//returncode")
    if code and code.strip() != "00":
        raise SourceError(f"API 오류({code.strip()}): {root.findtext('.//errmsg') or ''}")
    return root


def date_chunks(start: date, end: date, size: int = MAX_RANGE_DAYS, limit: int = MAX_CHUNKS
                ) -> list[tuple[date, date]]:
    """[start, end] 를 size 일 단위 구간으로 분할 (양 끝 포함)."""
    chunks = []
    cur = start
    while cur <= end and len(chunks) < limit:
        last = min(end, cur + timedelta(days=size - 1))
        chunks.append((cur, last))
        cur = last + timedelta(days=1)
    return chunks


def fetch(api_key: str, region: str, start: date, end: date, kids_only: bool = False) -> list[Activity]:
    base_params = {"service": api_key, "cpage": 1, "rows": ROWS}
    if code := REGIONS.get(region, {}).get("kopis"):
        base_params["signgucode"] = code
    if kids_only:
        base_params["kidstate"] = "Y"

    acts: dict[str, Activity] = {}
    for s, e in date_chunks(start, end):
        params = base_params | {"stdate": s.strftime("%Y%m%d"), "eddate": e.strftime("%Y%m%d")}
        root = _get_xml(f"{BASE}/pblprfr", params)
        for db in root.findall("db"):
            act = _from_list(db, kids_only)
            if act and act.id not in acts:
                acts[act.id] = act

    items = list(acts.values())
    run_parallel(lambda a: _enrich(api_key, a), items, deadline=DETAIL_DEADLINE, workers=15)
    return items


def _from_list(db: ET.Element, kids_only: bool) -> Activity | None:
    mt20id = _text(db, "mt20id")
    if not mt20id:
        return None
    genre = _text(db, "genrenm")
    return Activity(
        id=f"kopis:{mt20id}",
        source="KOPIS",
        title=_text(db, "prfnm"),
        category=f"공연·{genre}" if genre else "공연",
        start_date=_date(_text(db, "prfpdfrom")),
        end_date=_date(_text(db, "prfpdto")),
        region=_text(db, "area"),
        address=_text(db, "fcltynm") or None,
        description=genre,
        detail_url=DETAIL_PAGE.format(id=mt20id),
        image_url=to_https(_text(db, "poster") or None),
        tags=["아동"] if kids_only else [],
    )


def _enrich(api_key: str, act: Activity) -> None:
    """상세 정보로 가격·연령·예매처를 채운다. 실패하면 목록 정보 그대로 둔다."""
    mt20id = act.id.split(":", 1)[1]
    try:
        root = _get_xml(f"{BASE}/pblprfr/{mt20id}", {"service": api_key})
    except SourceError:
        return
    db = root.find("db")
    if db is None:
        return

    relates = [(_text(r, "relatenm"), _text(r, "relateurl")) for r in db.findall("relates/relate")]
    relates = [(n, u) for n, u in relates if u]
    price_text = _text(db, "pcseguidance")
    act.price_text = price_text or None
    act.price_min, act.price_max = parse_price(price_text)
    act.age_rating = _text(db, "prfage") or None
    act.duration = _text(db, "prfruntime") or None
    act.open_hours = _text(db, "dtguidance") or None
    act.description = " ".join(filter(None, [_text(db, "sty"), act.description]))
    if relates:
        act.booking_name, act.booking_url = relates[0]
    if _text(db, "child") == "Y" and "아동" not in act.tags:
        act.tags.append("아동")
