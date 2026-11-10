"""공통 데이터 모델과 시간 유틸리티."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

STATUS_UPCOMING = "예매 오픈 예정"
STATUS_OPEN = "예매 중"
STATUS_NOT_REQUIRED = "예매 불필요"
STATUS_UNKNOWN = "예매대기(미확인)"
BOOKING_STATUSES = [STATUS_UPCOMING, STATUS_OPEN, STATUS_NOT_REQUIRED, STATUS_UNKNOWN]


def now_kst() -> datetime:
    return datetime.now(KST)


@dataclass
class Activity:
    id: str                              # source + 원본 ID
    source: str                          # "KOPIS" | "서울시" | "TourAPI" | "예시"
    title: str
    category: str                        # 공연·뮤지컬 / 전시 / 축제 ...
    start_date: date | None = None
    end_date: date | None = None
    open_hours: str | None = None
    duration: str | None = None          # 소요시간 (공연 러닝타임 등)
    contact: str | None = None           # 문의처
    region: str = ""
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    price_text: str | None = None
    price_min: int | None = None         # 원, 무료=0, 미확인=None
    price_max: int | None = None
    age_rating: str | None = None
    target: str | None = None            # 이용 대상 (누구나, 어린이 ...)
    description: str = ""                # 키워드 매칭·예매일 추출용 텍스트
    booking_open_at: datetime | None = None   # 확인된 예매 오픈 일시 (KST)
    booking_time_known: bool = False     # 오픈 '시각'까지 확인됐는지
    booking_source: str | None = None    # "api" | "text"
    booking_required: bool | None = None # False=불필요 명시, True=필요, None=불명확
    booking_status: str = STATUS_UNKNOWN
    booking_url: str | None = None
    booking_name: str | None = None
    detail_url: str | None = None
    image_url: str | None = None
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def text_blob(self) -> str:
        parts = [self.title, self.category, self.description, self.target or "",
                 self.age_rating or "", " ".join(self.tags)]
        return " ".join(p for p in parts if p)
