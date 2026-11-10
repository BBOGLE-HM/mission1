"""서울 열린데이터광장 - 서울시 문화행사 정보 (culturalEventInfo). 서울 지역 전용.

※ openapi.seoul.go.kr:8088 은 https 연결을 지원하지 않아(2026-11 확인) http 를 사용한다.
   키가 평문으로 전송되므로 서울시 키는 이 API 전용으로 발급해 쓰는 것을 권장.
"""
from __future__ import annotations

from datetime import date, datetime

from core.models import Activity
from core.price_parser import parse_price
from sources.base import SourceError, http_get, run_parallel, to_https

URL = "http://openapi.seoul.go.kr:8088/{key}/json/culturalEventInfo/{start}/{end}/"
PAGE_SIZE = 1000   # 1회 최대 1000건 (sample 키는 5건)
MAX_PAGES = 3      # 최대 3000건
PAGE_DEADLINE = 4.0


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _coords(row: dict) -> tuple[float | None, float | None]:
    """LAT/LOT 필드가 뒤바뀐 경우가 있어 값 범위로 위도/경도를 판별."""
    vals = []
    for k in ("LAT", "LOT"):
        try:
            vals.append(float(row.get(k) or ""))
        except ValueError:
            pass
    lat = next((v for v in vals if 33 <= v <= 39), None)
    lon = next((v for v in vals if 124 <= v <= 132), None)
    return lat, lon


def _page(api_key: str, start: int, end: int) -> tuple[list[dict], int]:
    resp = http_get(URL.format(key=api_key, start=start, end=end))
    try:
        data = resp.json()
    except ValueError as e:
        raise SourceError("응답 형식 오류") from e
    payload = data.get("culturalEventInfo")
    if not payload:
        result = data.get("RESULT") or {}
        if result.get("CODE") == "INFO-200":  # 해당 데이터 없음
            return [], 0
        raise SourceError(f"API 오류({result.get('CODE', '?')}): {result.get('MESSAGE', '')}")
    return payload.get("row", []), int(payload.get("list_total_count") or 0)


def fetch(api_key: str) -> list[Activity]:
    if api_key == "sample":
        rows, _ = _page(api_key, 1, 5)
    else:
        rows, total = _page(api_key, 1, PAGE_SIZE)
        ranges = [(s, s + PAGE_SIZE - 1) for s in range(PAGE_SIZE + 1, min(total, PAGE_SIZE * MAX_PAGES) + 1, PAGE_SIZE)]
        for got in run_parallel(lambda r: _page(api_key, *r)[0], ranges, deadline=PAGE_DEADLINE, workers=3):
            rows.extend(got or [])
    return [_to_activity(row) for row in rows if row.get("TITLE")]


def _to_activity(row: dict) -> Activity:
    fee = (row.get("USE_FEE") or "").strip()
    price_min, price_max = parse_price(fee)
    if (row.get("IS_FREE") or "").strip() == "무료":
        price_min, price_max = 0, price_max or 0
    lat, lon = _coords(row)
    gu = (row.get("GUNAME") or "").strip()
    place = (row.get("PLACE") or "").strip()
    link = (row.get("ORG_LINK") or "").strip() or None
    portal = (row.get("HMPG_ADDR") or "").strip() or None

    return Activity(
        id=f"seoul:{row.get('TITLE')}:{row.get('STRTDATE', '')[:10]}",
        source="서울시",
        title=row["TITLE"].strip(),
        category=(row.get("CODENAME") or "문화행사").strip(),
        start_date=_date(row.get("STRTDATE")),
        end_date=_date(row.get("END_DATE")),
        region="서울",
        address=f"서울 {gu} {place}".strip(),
        lat=lat,
        lon=lon,
        price_text=fee or (row.get("IS_FREE") or None),
        price_min=price_min,
        price_max=price_max,
        target=(row.get("USE_TRGT") or "").strip() or None,
        contact=(row.get("ORG_NAME") or "").strip() or None,
        description=" ".join(filter(None, [
            row.get("PROGRAM"), row.get("ETC_DESC"), fee, row.get("USE_TRGT"),
        ])),
        detail_url=portal or link,
        booking_url=link if link and link != portal else None,
        image_url=to_https((row.get("MAIN_IMG") or "").strip() or None),
    )
