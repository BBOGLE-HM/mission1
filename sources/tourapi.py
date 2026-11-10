"""한국관광공사 TourAPI (KorService2) - 축제·행사.

목록: searchFestival2 (행사 기간), 상세: detailIntro2 (contentTypeId=15: 요금, 예매처, 연령)
serviceKey 는 공공데이터포털의 '디코딩(Decoding)' 키를 사용한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import quote

from core.models import Activity
from core.price_parser import parse_price
from core.regions import REGIONS
from sources.base import SourceError, http_get, run_parallel, to_https

BASE = "https://apis.data.go.kr/B551011/KorService2"
SEARCH_PAGE = "https://korean.visitkorea.or.kr/search/search_list.do?keyword={q}"
LOOKBACK_DAYS = 60  # 이미 시작해 진행 중인 행사까지 포함하기 위해 과거부터 조회
DETAIL_DEADLINE = 3.5  # 상세(요금·연령) 조회 전체 마감(초). 못 끝낸 항목은 가격 미확인으로 남김


def _common(api_key: str) -> dict:
    return {"serviceKey": api_key, "MobileOS": "ETC", "MobileApp": "NolgeotFinder", "_type": "json"}


def _items(resp) -> list[dict]:
    try:
        data = resp.json()
    except ValueError as e:
        raise SourceError(f"응답 형식 오류: {resp.text[:80]}") from e
    body = data.get("response", {})
    code = body.get("header", {}).get("resultCode")
    if code not in ("0000", "00"):
        raise SourceError(f"API 오류({code}): {body.get('header', {}).get('resultMsg', '')}")
    items = (body.get("body") or {}).get("items") or {}
    if not isinstance(items, dict):
        return []
    item = items.get("item") or []
    return item if isinstance(item, list) else [item]


def _date(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "").strip(), "%Y%m%d").date()
    except ValueError:
        return None


def fetch(api_key: str, region: str, start: date, end: date, rows: int = 200) -> list[Activity]:
    params = _common(api_key) | {
        "numOfRows": rows,
        "pageNo": 1,
        "arrange": "A",
        "eventStartDate": (start - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d"),
        "eventEndDate": end.strftime("%Y%m%d"),
    }
    if code := REGIONS.get(region, {}).get("ldong"):
        params["lDongRegnCd"] = code

    items = _items(http_get(f"{BASE}/searchFestival2", params))
    acts = [_to_activity(it) for it in items if it.get("title")]
    # 이미 종료된 행사는 상세 조회 전에 제외
    acts = [a for a in acts if not (a.end_date and a.end_date < start) and not (a.start_date and a.start_date > end)]
    run_parallel(lambda a: _safe_enrich(api_key, a), acts, deadline=DETAIL_DEADLINE, workers=15)
    return acts


def _to_activity(it: dict) -> Activity:
    def coord(k):
        try:
            return float(it.get(k) or "")
        except ValueError:
            return None

    title = it["title"].strip()
    return Activity(
        id=f"tour:{it.get('contentid')}",
        source="TourAPI",
        title=title,
        category="축제·행사",
        start_date=_date(it.get("eventstartdate")),
        end_date=_date(it.get("eventenddate")),
        region=(it.get("addr1") or "").split(" ")[0],
        address=" ".join(filter(None, [it.get("addr1"), it.get("addr2")])) or None,
        lat=coord("mapy"),
        lon=coord("mapx"),
        contact=(it.get("tel") or "").strip() or None,
        detail_url=SEARCH_PAGE.format(q=quote(title)),
        image_url=to_https(it.get("firstimage") or None),
    )


def _safe_enrich(api_key: str, act: Activity) -> None:
    try:
        _enrich(api_key, act)
    except SourceError:
        pass


def _enrich(api_key: str, act: Activity) -> None:
    content_id = act.id.split(":", 1)[1]
    params = _common(api_key) | {"contentId": content_id, "contentTypeId": 15}
    items = _items(http_get(f"{BASE}/detailIntro2", params))
    if not items:
        return
    it = items[0]
    fee = (it.get("usetimefestival") or "").replace("<br>", " ").strip()
    act.price_text = fee or None
    act.price_min, act.price_max = parse_price(fee)
    act.age_rating = (it.get("agelimit") or "").strip() or None
    act.open_hours = (it.get("playtime") or "").replace("<br>", " ").strip() or None
    act.duration = (it.get("spendtimefestival") or "").strip() or None
    act.contact = act.contact or (it.get("sponsor1tel") or "").strip() or None
    booking_place = (it.get("bookingplace") or "").strip()
    if booking_place:
        act.booking_required = True
        act.booking_name = booking_place
    act.description = " ".join(filter(None, [
        it.get("program"), it.get("subevent"), fee, booking_place,
    ])).replace("<br>", " ")
