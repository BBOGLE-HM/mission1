"""놀것찾기 - 검색 MVP (Streamlit)."""
from __future__ import annotations

import os
import threading
from datetime import date, datetime, timedelta

import streamlit as st

from core.booking import d_day_label, format_open_at
from core.hours import is_open_now
from core.models import (
    BOOKING_STATUSES,
    STATUS_NOT_REQUIRED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    STATUS_UPCOMING,
    Activity,
    now_kst,
)
from core.price_parser import format_price, has_partial_free
from core.recommender import AGE_GROUPS, load_themes
from core.regions import CENTERS, REGIONS
from core.search import SORT_OPTIONS, SearchParams, apply_view, district_options, process
from sources import demo, kopis, seoul, tourapi
from sources.base import collect_sources, safe_url

st.set_page_config(page_title="놀것찾기", page_icon="🎈", layout="centered")

PAGE_SIZE = 20
SEARCH_DEADLINE = 6.0  # 전체 소스 응답 대기 한도(초). 넘기면 해당 소스는 '응답 없음' 처리

# 예매 상태 → (뱃지 색, 아이콘, 지도 RGB). 색만으로 구분하지 않도록 뱃지에는 항상 텍스트를 함께 표시
STATUS_STYLE = {
    STATUS_UPCOMING: ("blue", "⏰", [37, 99, 235]),
    STATUS_OPEN: ("green", "✅", [22, 163, 74]),
    STATUS_NOT_REQUIRED: ("gray", "🚶", [107, 114, 128]),
    STATUS_UNKNOWN: ("orange", "❔", [234, 88, 12]),
}
CATEGORY_EMOJI = [
    ("동물", "🐾"), ("클래스", "🧩"), ("체험", "🧩"), ("사진", "📷"), ("전시", "🖼️"),
    ("미술", "🖼️"), ("축제", "🎉"), ("국악", "🥁"), ("클래식", "🎻"), ("음악", "🎵"),
    ("콘서트", "🎵"), ("교육", "📚"), ("뮤지컬", "🎭"), ("연극", "🎭"), ("공연", "🎭"),
]
WEEKDAYS = "월화수목금토일"

st.markdown(
    """
    <style>
    /* ── 신나는 배경: 알록달록한 색 번짐 + 움직이는 색종이 점무늬 (라이트/다크 공통, 반투명) ── */
    [data-testid="stApp"] {
      background-image:
        radial-gradient(circle at 10% 15%, rgba(255,107,107,.40) 0, transparent 32%),
        radial-gradient(circle at 90% 10%, rgba(255,200,60,.42) 0, transparent 30%),
        radial-gradient(circle at 85% 88%, rgba(6,214,160,.32) 0, transparent 34%),
        radial-gradient(circle at 18% 92%, rgba(118,120,237,.34) 0, transparent 34%),
        radial-gradient(circle at 55% 50%, rgba(255,120,200,.16) 0, transparent 42%),
        radial-gradient(circle, rgba(242,100,63,.45) 2px, transparent 2.8px),
        radial-gradient(circle, rgba(118,120,237,.40) 2px, transparent 2.8px),
        radial-gradient(circle, rgba(6,190,140,.38) 1.6px, transparent 2.4px);
      background-size: 100% 100%, 100% 100%, 100% 100%, 100% 100%, 100% 100%,
                       56px 56px, 56px 56px, 84px 84px;
      background-position: 0 0, 0 0, 0 0, 0 0, 0 0, 0 0, 28px 28px, 14px 42px;
      background-attachment: fixed;
      animation: party-drift 24s linear infinite;
    }
    @keyframes party-drift {
      to { background-position: 0 0, 0 0, 0 0, 0 0, 0 0, 56px 112px, 84px 140px, 98px 210px; }
    }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stMain"] { position: relative; z-index: 1; }  /* 장식은 콘텐츠 뒤로 */
    [data-testid="stSidebar"] > div:first-child {
      background-image: linear-gradient(165deg, rgba(255,200,60,.22) 0%, rgba(255,107,107,.14) 45%,
                                        rgba(118,120,237,.16) 100%);
    }
    /* 떠다니는 장식 */
    [data-testid="stApp"]::before, [data-testid="stApp"]::after {
      position: fixed; z-index: 0; pointer-events: none; font-size: 2.6rem; opacity: .55;
      animation: party-float 5s ease-in-out infinite;
    }
    [data-testid="stApp"]::before { content: "🎈"; top: 4.5rem; right: 2.2rem; }
    [data-testid="stApp"]::after  { content: "🎉"; bottom: 2rem; right: 2.6rem; animation-delay: -2.5s; }
    @keyframes party-float {
      0%, 100% { transform: translateY(0) rotate(-6deg); }
      50%      { transform: translateY(-14px) rotate(6deg); }
    }
    /* 배경 위에서도 카드 글자가 잘 읽히도록 */
    [data-testid="stVerticalBlockBorderWrapper"] { backdrop-filter: blur(6px); }
    @media (max-width: 640px) {
      [data-testid="stApp"]::before, [data-testid="stApp"]::after { display: none; }
    }
    @media (prefers-reduced-motion: reduce) {
      [data-testid="stApp"], [data-testid="stApp"]::before, [data-testid="stApp"]::after { animation: none; }
    }
    .thumb-ph {display:flex;align-items:center;justify-content:center;aspect-ratio:3/4;
               border-radius:0.75rem;font-size:3rem;background:rgba(242,100,63,0.12);}
    .empty-state {text-align:center;padding:1.5rem 0 0.5rem;}
    .empty-state .icon {font-size:3rem;}
    /* 모바일: 카드 컬럼이 세로로 쌓이므로 썸네일이 화면을 덮지 않도록 높이 제한 */
    @media (max-width: 640px) {
      .thumb-ph {aspect-ratio:auto;height:96px;font-size:2.5rem;}
      [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stImage"] img
        {max-height:200px;width:100%;object-fit:cover;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ───────────────────────── 설정 / 시크릿 ─────────────────────────
def get_secret(name: str) -> str:
    try:
        value = st.secrets.get(name)
    except Exception:  # secrets.toml 이 없을 때
        value = None
    return (value or os.environ.get(name) or "").strip()


KEYS = {
    "kopis": get_secret("KOPIS_API_KEY"),
    "tour": get_secret("TOUR_API_KEY"),
    "seoul": get_secret("SEOUL_API_KEY"),
}
HAS_ANY_KEY = any(KEYS.values())


# ───────────────────────── 소스 호출 (10분 캐시) ─────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def cached_kopis(key: str, region: str, start: date, end: date, kids_only: bool):
    return kopis.fetch(key, region, start, end, kids_only=kids_only)


@st.cache_data(ttl=600, show_spinner=False)
def cached_seoul(key: str):
    return seoul.fetch(key)


@st.cache_data(ttl=600, show_spinner=False)
def cached_tour(key: str, region: str, start: date, end: date):
    return tourapi.fetch(key, region, start, end)


def _with_ctx(fn):
    """스레드에서도 Streamlit 캐시가 경고 없이 동작하도록 실행 컨텍스트 전달."""
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
        ctx = get_script_run_ctx()
    except Exception:
        return fn

    def wrapper():
        add_script_run_ctx(threading.current_thread(), ctx)
        return fn()
    return wrapper


def collect(region: str, start: date, end: date, kids_only: bool, use_demo: bool, today: date):
    jobs = {}
    if KEYS["kopis"]:
        jobs["KOPIS(공연)"] = lambda: cached_kopis(KEYS["kopis"], region, start, end, kids_only)
    if KEYS["tour"]:
        jobs["TourAPI(축제)"] = lambda: cached_tour(KEYS["tour"], region, start, end)
    if KEYS["seoul"] and region == "서울":
        jobs["서울시 문화행사"] = lambda: cached_seoul(KEYS["seoul"])

    acts, status = collect_sources({n: _with_ctx(f) for n, f in jobs.items()}, SEARCH_DEADLINE)
    if use_demo:
        got = demo.fetch(region, today)
        acts.extend(got)
        status["예시 데이터"] = f"{len(got)}건"
    return acts, status


# ───────────────────────── 표시용 헬퍼 ─────────────────────────
_MD_SPECIAL = str.maketrans({c: "\\" + c for c in "\\`*_[]<>#~$|:"})


def md(text) -> str:
    """외부 데이터의 마크다운 특수문자 이스케이프."""
    return str(text).translate(_MD_SPECIAL)


def status_badge(status: str, suffix: str = "") -> str:
    color, icon, _ = STATUS_STYLE[status]
    return f":{color}-badge[{icon} {status}{suffix}]"


def category_emoji(a: Activity) -> str:
    text = f"{a.category} {a.title}"
    return next((e for kw, e in CATEGORY_EMOJI if kw in text), "🎈")


def period_text(a: Activity) -> str:
    if a.start_date and a.end_date:
        if a.start_date == a.end_date:
            return f"{a.start_date:%Y.%m.%d}"
        return f"{a.start_date:%Y.%m.%d} ~ {a.end_date:%Y.%m.%d}"
    if a.start_date:
        return f"{a.start_date:%Y.%m.%d} ~"
    if a.end_date:
        return f"~ {a.end_date:%Y.%m.%d}"
    return "상시"


def booking_md(a: Activity, today: date) -> str:
    if a.booking_status == STATUS_UPCOMING and a.booking_open_at:
        days = (a.booking_open_at.date() - today).days
        dday = d_day_label(a.booking_open_at, today)
        dday_badge = f":red-badge[🔥 {dday}]" if days <= 3 else f":blue-badge[{dday}]"
        return f"{status_badge(a.booking_status)} **{format_open_at(a.booking_open_at, a.booking_time_known)}** {dday_badge}"
    if a.booking_status == STATUS_OPEN:
        when = f" {format_open_at(a.booking_open_at, a.booking_time_known)} 오픈" if a.booking_open_at else ""
        return f"{status_badge(a.booking_status)}{when}"
    if a.booking_status == STATUS_NOT_REQUIRED:
        return f"{status_badge(a.booking_status)} 현장 입장 가능"
    return f"{status_badge(a.booking_status)} 원문에서 확인 필요"


def open_now_badge(a: Activity, now: datetime) -> str:
    """오늘 진행 중인 항목만 '지금 운영 중' 여부 표시 (운영시간을 해석할 수 있을 때)."""
    today = now.date()
    if (a.start_date and a.start_date > today) or (a.end_date and a.end_date < today):
        return ""
    state = is_open_now(a.open_hours, now)
    if state is True:
        return ":green-badge[🟢 지금 운영 중]"
    if state is False:
        return ":gray-badge[지금은 운영 시간 아님]"
    return ""


def period_range(preset: str, today: date) -> tuple[date, date]:
    if preset == "오늘":
        return today, today
    if preset == "이번 주말":
        if today.weekday() >= 5:  # 토/일
            return today, today + timedelta(days=6 - today.weekday())
        sat = today + timedelta(days=5 - today.weekday())
        return sat, sat + timedelta(days=1)
    return today, today + timedelta(days=14)


def picked_range(picked, today: date) -> tuple[date, date]:
    """date_input 결과 → (시작, 종료). 하루만 고르면 그 하루."""
    if isinstance(picked, (tuple, list)):
        if len(picked) == 2:
            return picked[0], picked[1]
        if len(picked) == 1:
            return picked[0], picked[0]
        return today, today
    return picked, picked


# ───────────────────────── 사이드바 ─────────────────────────
THEMES = load_themes()
now = now_kst()
today = now.date()

with st.sidebar:
    st.markdown("## 🔎 무엇을 하고 놀까?")

    st.markdown("#### 👥 누구와")
    theme_key = st.radio("누구와 함께?", list(THEMES), format_func=lambda k: THEMES[k].label,
                         label_visibility="collapsed")
    theme = THEMES[theme_key]
    child_age_max = None
    default_people = 1 if theme_key == "solo" else 2
    if theme.kids:
        c1, c2 = st.columns(2)
        age_label = c1.selectbox("아이 연령", list(AGE_GROUPS), index=1)
        child_age_max = AGE_GROUPS[age_label]
        people = c2.number_input("인원 수", min_value=1, max_value=20, value=default_people)
    else:
        people = st.number_input("인원 수", min_value=1, max_value=20, value=default_people)

    st.markdown("#### 📍 어디서")
    region = st.selectbox("지역", list(REGIONS), index=0, label_visibility="collapsed")

    st.markdown("#### 📅 언제")
    preset = st.radio("기간", ["오늘", "이번 주말", "향후 2주", "직접 선택"], index=2,
                      horizontal=True, label_visibility="collapsed")
    if preset == "직접 선택":
        picked = st.date_input("기간 선택", value=(today, today + timedelta(days=7)), min_value=today)
        start, end = picked_range(picked, today)
    else:
        start, end = period_range(preset, today)
    st.caption(f"{start:%m/%d}({WEEKDAYS[start.weekday()]}) ~ {end:%m/%d}({WEEKDAYS[end.weekday()]})")
    if (end - start).days >= 93:
        st.caption("공연(KOPIS)은 앞쪽 93일까지만 조회돼요.")

    st.markdown("#### 💰 예산")
    unit = st.radio("예산 기준", ["1인당", "총액"], horizontal=True, label_visibility="collapsed")
    free_only = st.toggle("무료만 보기")
    budget = st.slider("허용 예산", 0, 300_000, 50_000, step=5_000, format="%d원",
                       disabled=free_only, label_visibility="collapsed")
    if free_only:
        st.caption("무료 항목만 보여드려요")
    elif unit == "1인당":
        st.caption(f"1인당 **{budget:,}원** 이하")
    else:
        st.caption(f"{int(people)}명 합계 **{budget:,}원** 이하")
    include_unknown = st.toggle("가격 미확인 항목도 보기")

    with st.expander("⚙️ 보기 옵션"):
        statuses = st.multiselect("예매 상태", BOOKING_STATUSES, default=BOOKING_STATUSES,
                                  placeholder="예매 상태를 선택하세요")
        if not statuses:
            st.warning("예매 상태를 하나 이상 선택해야 결과가 보여요.", icon="⚠️")
        sort = st.selectbox("정렬", SORT_OPTIONS)
        st.caption("예매 상태·정렬은 다시 검색하지 않아도 바로 적용돼요.")
        use_demo = st.toggle("예시 데이터 포함", value=not HAS_ANY_KEY,
                             help="API 키가 없어도 화면을 확인할 수 있는 예시 데이터")

    run = st.button("🔍 놀거리 찾기", type="primary", width="stretch")


# ───────────────────────── 검색 실행 ─────────────────────────
params = SearchParams(
    region=region, start=start, end=end, budget=budget, people=int(people),
    per_person=(unit == "1인당"), free_only=free_only, include_unknown_price=include_unknown,
    child_age_max=child_age_max,
)
query_sig = (theme_key, use_demo, params)

if run or "results" not in st.session_state:  # 첫 실행 시 기본 조건으로 자동 검색
    with st.spinner("🎈 지금 기준으로 놀거리를 찾고 있어요..."):
        raw, source_status = collect(region, start, end, theme.kids, use_demo, today)
        results = process(raw, params, theme, now)
    st.session_state.update(
        results=results, source_status=source_status, searched_at=now,
        searched_theme=theme.label, searched_sig=query_sig, shown=PAGE_SIZE,
    )
    st.session_state.pop("districts", None)


# ───────────────────────── 카드 / 지도 ─────────────────────────
def render_card(a: Activity, at: datetime) -> None:
    with st.container(border=True):
        left, right = st.columns([1, 2.8], gap="medium")
        with left:
            if a.image_url:
                st.image(a.image_url, width="stretch")
            else:
                st.markdown(f"<div class='thumb-ph'>{category_emoji(a)}</div>", unsafe_allow_html=True)
        with right:
            st.markdown(f"**{md(a.title)}**")
            st.caption(" · ".join(md(x) for x in [a.category, a.address, f"출처 {a.source}"] if x))
            price = format_price(a.price_min, a.price_max)
            if a.price_min and has_partial_free(a.price_text):
                price += " (일부 대상 무료)"
            open_badge = open_now_badge(a, at)
            st.markdown(f"📅 {period_text(a)} {open_badge}  \n💰 **{md(price)}**")
            st.markdown(booking_md(a, at.date()))
            if a.reasons:
                st.markdown(" ".join(f":violet-badge[{md(r)}]" for r in a.reasons))

            links = []
            if url := safe_url(a.detail_url):
                links.append(("상세 보기", url, "secondary", ":material/open_in_new:"))
            if url := safe_url(a.booking_url):
                label = f"예매처 · {a.booking_name}" if a.booking_name else "예매처"
                kind = "primary" if a.booking_status in (STATUS_OPEN, STATUS_UPCOMING) else "secondary"
                links.append((label[:20], url, kind, ":material/confirmation_number:"))
            if links:
                for col, (label, url, kind, icon) in zip(st.columns(len(links)), links):
                    col.link_button(label, url, type=kind, icon=icon, width="stretch")

        with st.expander("자세히 보기"):
            rows = {
                "운영 시간": a.open_hours,
                "소요 시간": a.duration,
                "관람 등급": a.age_rating,
                "이용 대상": a.target,
                "가격 안내(원문)": a.price_text,
                "문의처": a.contact,
                "예매 상태": a.booking_status,
                "예매일 출처": {"api": "API 제공", "text": "안내문에서 추출"}.get(a.booking_source or ""),
            }
            shown_any = False
            for k, v in rows.items():
                if v:
                    st.markdown(f"- **{k}**: {md(v)}")
                    shown_any = True
            if not shown_any:
                st.caption("추가 정보가 없어요.")


def render_map(results: list[Activity], region: str) -> None:
    pts = [a for a in results if a.lat is not None and a.lon is not None]
    if not pts:
        st.info("지도에 표시할 좌표 정보가 있는 결과가 없어요. (서울시·TourAPI 데이터에서 좌표를 제공해요)", icon="🗺️")
        return
    import pydeck as pdk

    data = [{
        "lat": a.lat, "lon": a.lon, "title": a.title, "status": a.booking_status,
        "price": format_price(a.price_min, a.price_max), "color": STATUS_STYLE[a.booking_status][2],
    } for a in pts]
    lat = sum(p["lat"] for p in data) / len(data) if data else CENTERS[region][0]
    lon = sum(p["lon"] for p in data) / len(data) if data else CENTERS[region][1]
    layer = pdk.Layer(
        "ScatterplotLayer", data, get_position="[lon, lat]", get_fill_color="color",
        get_radius=150, radius_min_pixels=7, radius_max_pixels=14, pickable=True,
        stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2,
    )
    st.pydeck_chart(pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=11),
        tooltip={"text": "{title}\n{status} · {price}"},
    ), height=420)
    st.markdown(" ".join(status_badge(s) for s in BOOKING_STATUSES))
    st.caption(f"좌표가 있는 {len(pts)}건만 표시돼요. 점에 마우스를 올리면 정보가 보여요.")


# ───────────────────────── 메인 화면 ─────────────────────────
searched_at: datetime = st.session_state["searched_at"]
sig_theme, _, sp = st.session_state["searched_sig"]

st.title("🎈 놀것찾기", anchor=False)
st.markdown("지금 이 순간 갈 수 있는 놀거리를 **누구와 함께**, **예산 안에서** 찾아드려요.")
st.markdown(
    f":orange-badge[🕒 기준 시각: {searched_at:%Y-%m-%d %H:%M} (KST)] "
    f":violet-badge[{md(st.session_state['searched_theme'])}] "
    f":blue-badge[📍 {md(sp.region)}] "
    f":green-badge[📅 {sp.start:%m/%d} ~ {sp.end:%m/%d}] "
    + (":gray-badge[무료만]" if sp.free_only else
       f":gray-badge[💰 {'1인당' if sp.per_person else '총'} {sp.budget:,}원 이하]")
)
st.caption("검색 조건은 왼쪽 사이드바에서 바꿀 수 있어요 (모바일은 왼쪽 위 **»** 버튼).")

if query_sig != st.session_state["searched_sig"]:
    st.info("검색 조건이 바뀌었어요. 사이드바의 **🔍 놀거리 찾기**를 눌러 반영하세요.", icon="✏️")

if not HAS_ANY_KEY:
    st.info("API 키가 설정되지 않아 **예시 데이터**로 보여드리고 있어요. "
            "`.streamlit/secrets.toml`에 키를 넣으면 실제 데이터가 나와요 (README 참고).", icon="🔑")

source_status: dict[str, str] = st.session_state["source_status"]
source_rows = {n: s for n, s in source_status.items() if not n.startswith("_")}
failed = {n: s for n, s in source_rows.items() if s.startswith("⚠️")}
if failed:
    st.warning("일부 데이터 소스가 응답하지 않아 나머지 결과만 보여드려요.  \n"
               + "  \n".join(f"- {md(n)}: {md(s)}" for n, s in failed.items()), icon="⚠️")

all_results: list[Activity] = st.session_state["results"]

# 시/군/구 좁히기 (PRD F4) — 검색 결과 주소에서 추출, 선택하지 않으면 전체
district_choices = district_options(all_results)
districts = None
if len(district_choices) > 1:
    picked_d = st.pills("📍 시/군/구로 좁히기 (선택하지 않으면 전체)", district_choices,
                        selection_mode="multi", key="districts")
    districts = picked_d or None

results = apply_view(all_results, statuses=statuses, districts=districts, sort=sort)

if results:
    counts = {s: sum(1 for a in results if a.booking_status == s) for s in BOOKING_STATUSES}
    st.markdown(f"#### {len(results)}건을 찾았어요")
    st.markdown(" ".join(status_badge(s, f" {c}") for s, c in counts.items() if c))

    tab_list, tab_map = st.tabs(["📋 리스트", "🗺️ 지도"])
    with tab_list:
        shown = st.session_state["shown"]
        for a in results[:shown]:
            render_card(a, searched_at)
        if shown < len(results):
            if st.button(f"더 보기 ({len(results) - shown}건 남음)", width="stretch"):
                st.session_state["shown"] += PAGE_SIZE
                st.rerun()
    with tab_map:
        render_map(results, sp.region)
else:
    with st.container(border=True):
        st.markdown(
            "<div class='empty-state'><div class='icon'>🔍</div>"
            "<b>조건에 맞는 놀거리를 찾지 못했어요</b></div>",
            unsafe_allow_html=True,
        )
        tips = []
        if not statuses:
            tips.append("보기 옵션에서 예매 상태를 하나 이상 선택해 주세요")
        elif len(statuses) < len(BOOKING_STATUSES):
            tips.append("보기 옵션의 예매 상태 필터를 넓혀 보세요")
        if districts:
            tips.append("시/군/구 선택을 해제해 보세요")
        if sp.free_only:
            tips.append("'무료만 보기'를 꺼 보세요")
        elif sp.budget < 300_000:
            tips.append("예산을 조금 늘려 보세요")
        if not sp.include_unknown_price:
            tips.append("'가격 미확인 항목도 보기'를 켜 보세요")
        if (sp.end - sp.start).days < 14:
            tips.append("기간을 '향후 2주'로 넓혀 보세요")
        tips.append("다른 지역이나 테마도 확인해 보세요")
        st.markdown("\n".join(f"- {t}" for t in tips))

with st.expander("데이터 소스 상태"):
    if source_rows:
        for name, s in source_rows.items():
            st.markdown(f"- **{md(name)}**: {md(s)}")
        if "_elapsed" in source_status:
            st.caption(f"외부 API 응답 시간: {source_status['_elapsed']} (한도 {SEARCH_DEADLINE:.0f}초)")
    else:
        st.markdown("- 사용 가능한 소스가 없어요. API 키를 설정하거나 보기 옵션에서 '예시 데이터 포함'을 켜 주세요.")

st.caption("데이터 출처: KOPIS 공연예술통합전산망 · 한국관광공사 TourAPI · 서울 열린데이터광장  \n"
           "가격·예매일정은 바뀔 수 있으니 예매 전 원문을 꼭 확인하세요.")
