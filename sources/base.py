"""외부 API 호출 공통 유틸."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable, Iterable, TypeVar

import requests

TIMEOUT = 5  # PRD: 소스별 요청 타임아웃 5초
_HEADERS = {"User-Agent": "nolgeot-finder/0.1"}

T = TypeVar("T")
R = TypeVar("R")


class SourceError(Exception):
    """소스 API 호출/응답 오류 (사용자에게 안내 메시지로 노출)."""


def http_get(url: str, params: dict | None = None, timeout: float = TIMEOUT) -> requests.Response:
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.Timeout as e:
        raise SourceError("응답 시간 초과") from e
    except requests.RequestException as e:
        # 예외 문자열에는 키가 포함된 URL이 들어갈 수 있어 클래스명만 노출
        raise SourceError(f"요청 실패: {e.__class__.__name__}") from e
    return resp


def run_parallel(fn: Callable[[T], R], items: Iterable[T], deadline: float,
                 workers: int = 10) -> list[R | None]:
    """items 를 병렬 처리하되 deadline(초)이 지나면 기다리지 않고 미완료 항목은 None.

    ThreadPoolExecutor 를 with 블록으로 쓰면 종료 시 모든 스레드를 기다리므로
    shutdown(wait=False) 로 직접 정리한다. (이미 실행 중인 스레드는 백그라운드에서 끝까지 돈다)
    """
    items = list(items)
    if not items:
        return []
    ex = ThreadPoolExecutor(max_workers=min(workers, len(items)))
    try:
        futures = [ex.submit(fn, it) for it in items]
        wait(futures, timeout=deadline)
        out: list[R | None] = []
        for f in futures:
            if f.done() and not f.cancelled() and f.exception() is None:
                out.append(f.result())
            else:
                out.append(None)
        return out
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def collect_sources(jobs: dict[str, Callable[[], list]], deadline: float
                    ) -> tuple[list, dict[str, str]]:
    """여러 소스를 동시에 호출. 실패·시간 초과 소스는 상태 메시지만 남기고 나머지 결과는 반환."""
    names = list(jobs)
    results: dict[str, object] = {}

    def call(name: str):
        try:
            results[name] = jobs[name]()
        except Exception as e:  # noqa: BLE001 - 소스별 오류는 화면 안내로 처리
            results[name] = e

    started = time.monotonic()
    run_parallel(call, names, deadline=deadline, workers=len(names) or 1)
    acts: list = []
    status: dict[str, str] = {}
    for name in names:
        got = results.get(name)
        if got is None:
            status[name] = f"⚠️ 응답 없음 ({deadline:.0f}초 초과)"
        elif isinstance(got, Exception):
            msg = str(got) if isinstance(got, SourceError) else got.__class__.__name__
            status[name] = f"⚠️ 응답 없음 ({msg})"
        else:
            acts.extend(got)
            status[name] = f"{len(got)}건"
    status["_elapsed"] = f"{time.monotonic() - started:.1f}초"
    return acts, status


def to_https(url: str | None) -> str | None:
    if url and url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url or None


def safe_url(url: str | None) -> str | None:
    """http/https 링크만 허용 (javascript: 등 차단)."""
    if not url:
        return None
    url = url.strip()
    return url if url.lower().startswith(("http://", "https://")) else None
