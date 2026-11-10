"""API 키 없이 화면을 확인하기 위한 예시 데이터.

날짜는 실행 시점 기준 상대값으로 생성되어 항상 4가지 예매 상태가 모두 나오도록 구성한다.
"""
from __future__ import annotations

from datetime import date, timedelta

from core.models import Activity
from core.price_parser import parse_price
from core.regions import CENTERS


DISTRICTS = {"서울": ["종로구", "마포구", "강남구", "송파구", "용산구"],
             "경기": ["수원시", "성남시", "고양시", "용인시"]}


def _fmt(d: date, hm: str = "") -> str:
    return f"{d:%Y.%m.%d}" + (f" {hm}" if hm else "")


def fetch(region: str, today: date) -> list[Activity]:
    t = today
    D = lambda n: t + timedelta(days=n)  # noqa: E731

    rows = [
        # (제목, 분류, 시작, 종료, 가격문구, 관람등급, 이용대상, 설명, 태그)
        ("[예시] 어린이 인형극 '숲속 친구들'", "공연·아동", D(10), D(40), "전석 15,000원", "만 3세 이상", None,
         f"가족 인형극. 티켓오픈: {_fmt(D(2), '14:00')} 인터파크 단독", ["아동"]),
        ("[예시] 가족 과학 체험전", "전시·체험", D(-20), D(60), "1인 12,000원", "전체관람가", "누구나",
         "어린이 과학 체험. 예약 없이 현장 입장 가능합니다.", []),
        ("[예시] 국악 한마당 '가을의 소리'", "공연·한국음악(국악)", D(5), D(6), "전석 30,000원", "만 8세 이상", None,
         f"전통 국악 공연. 예매 오픈 {_fmt(D(-3), '10:00')}", []),
        ("[예시] 수목원 국화 축제", "축제", D(-5), D(12), "무료", None, "누구나",
         "가을 국화 정원 자유 관람", []),
        ("[예시] 뮤지컬 '별빛 정거장'", "공연·뮤지컬", D(20), D(80), "R석 120,000원, S석 90,000원", "만 13세 이상", None,
         "로맨틱 뮤지컬. 예매 일정은 추후 공지", []),
        ("[예시] 한강 야경 불꽃 공연", "축제", D(3), D(3), "무료", None, "누구나",
         "야경과 함께하는 불꽃 공연", []),
        ("[예시] 도자기 공방 원데이 클래스", "체험·클래스", D(7), D(30), "1인 45,000원", "만 10세 이상", None,
         f"공방 클래스. 사전예약 필수, 예약 오픈 {_fmt(D(1), '오전 10시')}", []),
        ("[예시] 인디 록 페스티벌", "공연·대중음악", D(9), D(10), "1일권 66,000원", "만 15세 이상", None,
         f"페스티벌 라인업 공개! 티켓 오픈 {_fmt(D(-10), '20:00')}", []),
        ("[예시] 사진전 '도시의 시간'", "전시", D(-30), D(25), "8,000원", "전체관람가", None,
         "도시 사진 전시. 현장 관람 가능", []),
        ("[예시] 클래식 실내악 리사이틀", "공연·서양음악(클래식)", D(4), D(4), "전석 20,000원", "만 7세 이상", None,
         "실내악 공연", []),
        ("[예시] 동물 교감 체험 농장", "체험", None, None, "입장료 10,000원", "24개월 이상", "가족",
         "동물 먹이주기 체험. 별도 예약 없이 이용 가능", []),
        ("[예시] 동네 골목 축제", "축제", D(1), D(2), None, None, "누구나",
         "골목 축제와 플리마켓", []),
        ("[예시] 지난 주말 재즈 공연 (종료됨)", "공연·대중음악", D(-10), D(-1), "30,000원", None, None,
         "이미 종료된 행사 — 결과에 나오지 않아야 함", []),
    ]

    # 항목별 추가 정보: (운영시간, 소요시간, 문의처)
    extras = {
        1: ("10:00 ~ 18:00 (매주 월요일 휴관)", "약 90분", "02-000-0001"),
        3: ("09:00 ~ 18:00", None, "02-000-0003"),
        4: (None, "150분 (인터미션 20분)", "1544-0000"),
        8: ("10:00 ~ 19:00", "약 60분", None),
        10: ("10:00 ~ 17:00", "약 120분", "031-000-0010"),
        11: ("19:00 ~ 23:30", None, None),
    }
    districts = DISTRICTS.get(region, ["중구", "동구", "서구", "남구", "북구"])
    c_lat, c_lon = CENTERS.get(region, CENTERS["서울"])
    acts = []
    for i, (title, cat, s, e, fee, age, target, desc, tags) in enumerate(rows):
        pmin, pmax = parse_price(fee)
        # 지도 확인용: 지역 중심 주변에 흩뿌린 예시 좌표
        lat = c_lat + ((i * 37) % 11 - 5) * 0.008
        lon = c_lon + ((i * 53) % 13 - 6) * 0.01
        acts.append(Activity(
            id=f"demo:{i}",
            source="예시",
            title=title,
            category=cat,
            start_date=s,
            end_date=e,
            region=region,
            address=f"{region} {districts[i % len(districts)]} 예시 장소 {i + 1}",
            lat=lat,
            lon=lon,
            open_hours=extras.get(i, (None,) * 3)[0],
            duration=extras.get(i, (None,) * 3)[1],
            contact=extras.get(i, (None,) * 3)[2],
            price_text=fee,
            price_min=pmin,
            price_max=pmax,
            age_rating=age,
            target=target,
            description=desc,
            detail_url=None,
            tags=list(tags),
        ))
    return acts
