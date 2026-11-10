# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

놀것찾기 — a Streamlit app that searches Korean public culture/event APIs **at run time (KST)** and filters results by companion theme (아이/부모님/연인/친구/혼자), budget, region and period, and shows a booking-schedule status per item. `PRD.md` is the source of truth for product rules; `docs/REVIEW.md` records the PRD compliance review and why several rules below exist. User-facing text, docs and comments are in Korean.

## Commands (Windows, project venv at `.venv`)

```powershell
.\.venv\Scripts\pip install -r requirements.txt pytest     # setup
.\.venv\Scripts\streamlit run app.py                        # run app
.\.venv\Scripts\python -m pytest -q tests                   # all tests
.\.venv\Scripts\python -m pytest -q tests/test_fixes.py::test_is_open_now   # single test
```

- Headless smoke test of the whole app: `streamlit.testing.v1.AppTest.from_file("app.py").run()` and check `at.exception`. AppTest does not apply CSS/theme, so visual changes must be checked in a real browser (e.g. Playwright at 1280px and 390px, light and dark).
- If a running dev server shows a `TokenError`/`EOF in multi-line string` right after editing `app.py`, it read the file mid-save — reload the page before debugging.
- Without API keys the app falls back to `sources/demo.py` (dates are generated relative to today, so all 4 booking statuses always appear). Real Seoul data can be tested with `SEOUL_API_KEY=sample` (5 rows only).
- API keys are read from `.streamlit/secrets.toml` (see `.example`) or env vars: `KOPIS_API_KEY`, `TOUR_API_KEY` (data.go.kr **decoding** key), `SEOUL_API_KEY`.
- Streamlit is pinned `>=1.67`: the UI relies on `:color-badge[]` markdown, `width="stretch"`, and `[theme.light]/[theme.dark]` in `.streamlit/config.toml`; older versions crash on image cards.

## Architecture

Data flow: `sources/*` fetch → normalized `core.models.Activity` → `core.search.process()` → stored in `st.session_state` → `core.search.apply_view()` at render time.

- **`sources/`** — one adapter per API (`kopis.py` performances, `tourapi.py` festivals, `seoul.py` Seoul-only events, `demo.py`). Each returns `list[Activity]`; list data first, then per-item detail enrichment (price, age, booking link) done via `sources.base.run_parallel` under a **deadline** — items whose detail didn't finish stay with unknown price rather than blocking. `app.collect()` calls sources through `collect_sources()` with an overall `SEARCH_DEADLINE`; a slow/failed source becomes a "⚠️ 응답 없음" status, never an exception. Do not use `with ThreadPoolExecutor()` for this (it waits for all threads on exit) — use `run_parallel`.
- Source calls are wrapped in `@st.cache_data(ttl=600)` in `app.py`; cached results are copies, and **booking status is recomputed on every search** from the search time, so never store time-dependent state in the sources.
- **`core/search.py`** — `process()` does dedupe (title normalized, leading `[기관명]` stripped) → region → period → `annotate_booking` → theme exclusion → budget → score. Status filter, 시/군/구 filter and sort are deliberately **not** in `process()`; they live in `apply_view()` so they apply instantly without re-searching. In `apply_view`, `None` = all, empty list = nothing.
- **`core/booking.py`** — booking status priority: confirmed open date (`예매 오픈 예정`/`예매 중`) → explicitly not required (`예매 불필요`) → `예매대기(미확인)`. Open dates are extracted from text only when unambiguous: a date must follow the keyword with only a separator/label between (`_KW_GAP`), dates meaning "until/마감" are rejected, multiple candidates → unknown, missing year resolved only against the event start date. The PRD rule is "never print an unconfirmed booking date"; prefer returning unknown over guessing.
- **`core/price_parser.py`** — `price_min` is the lowest **paid** price; 0 means fully free. Partial-free ("성인 12,000원 / 영유아 무료") is flagged via `has_partial_free()`, not by setting min to 0 (that would leak paid events into "무료만 보기"/budget).
- **`core/recommender.py`** + `themes.yaml` (keywords/exclude/penalty per theme) + `scoring.yaml` (weights). Korean keywords match as substrings, so exclusion words must be specific (`나이트클럽`, not `클럽`). Age limits come from `parse_min_age()` on `age_rating`/`target` (only "N세/개월 이상" are minimums), not from exclude words.
- **`core/filters.py`** — region match uses the **first token** of region/address (so "경기도 광주시" ≠ 광주). 시/군/구 is not an API parameter; it is extracted from result addresses (`district_of`).
- **`core/regions.py`** — per-region KOPIS `signgucode`, TourAPI `lDongRegnCd`, address aliases and map centers. KOPIS/TourAPI codes and response fields are not yet verified against real keys (see `docs/REVIEW.md` §4).

## Conventions

- All times use `core.models.now_kst()` / `KST` (`zoneinfo`, needs `tzdata` on Windows).
- Styling: theme colors/fonts are in `.streamlit/config.toml` (separate light/dark); everything else (festive background, floating 🎈🎉, card blur, mobile thumbnail limits) is one `<style>` block at the top of `app.py` targeting Streamlit `data-testid` selectors (`stApp`, `stMain`, `stSidebar`, `stVerticalBlockBorderWrapper`). Use only semi-transparent rgba colors there so one CSS works on both themes, and re-check these selectors after a Streamlit upgrade.
- Booking status badge colors/icons are defined once in `app.STATUS_STYLE` (blue/green/gray/orange per PRD F6) and reused by cards, counts and the map.
- External text rendered with `st.markdown` must go through `app.md()` (markdown escape); external links through `sources.base.safe_url()`. HTML (`unsafe_allow_html`) is used only for static strings.
- Error messages from sources must not include request URLs (keys are in query strings) — `http_get` only exposes the exception class name.
- Seoul API (`:8088`) does not support https; KOPIS uses https.
- `tests/test_review_repro.py` holds regression tests for bugs found in the review; keep them passing.
- `PROMPTS.md` contains the staged development prompts (skeleton → features → UI → review) used to build this project.
