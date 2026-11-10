# 🎈 놀것찾기

실행 시점(KST) 기준으로 **테마(누구와 함께)** 와 **허용 예산**에 맞는 놀거리를 찾아주고,
예매일정을 `예매 오픈 예정` / `예매 중` / `예매 불필요` / `예매대기(미확인)` 으로 안내하는 Streamlit 앱입니다.
자세한 요구사항은 [PRD.md](PRD.md) 참고.

## 실행

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\streamlit run app.py
```

API 키가 없으면 **예시 데이터**로 화면이 동작합니다.

## API 키 설정

`.streamlit/secrets.toml.example` 을 `.streamlit/secrets.toml` 로 복사한 뒤 키를 입력하세요. 키가 없는 소스는 건너뜁니다.

| 키 | 발급처 | 데이터 |
|---|---|---|
| `KOPIS_API_KEY` | KOPIS 공연예술통합전산망 › Open API | 공연 (가격·관람연령·예매처) |
| `TOUR_API_KEY` | 공공데이터포털 › 한국관광공사_국문 관광정보 서비스_GW (**디코딩 키**) | 축제·행사 |
| `SEOUL_API_KEY` | 서울 열린데이터광장 › 서울시 문화행사 정보 (`sample` 입력 시 5건 테스트) | 서울 문화행사 |

배포(Streamlit Community Cloud) 시에는 앱 설정의 **Secrets** 에 같은 형식으로 입력합니다.

## 테스트

```powershell
.\.venv\Scripts\pip install pytest
.\.venv\Scripts\python -m pytest -q tests
```

## 구조

```
app.py               Streamlit 화면 (사이드바 조건, 결과 카드)
core/models.py       Activity 데이터 모델, 예매 상태 상수
core/price_parser.py 가격 문자열 → 최저/최고가
core/booking.py      예매일 추출, 예매 불필요 판정, 예매 상태
core/filters.py      날짜·예산·지역 필터
core/recommender.py  테마 추천 점수 (themes.yaml)
core/search.py       검색 파이프라인 (중복 제거 → 필터 → 점수 → 정렬)
sources/             KOPIS, TourAPI, 서울시, 예시 데이터
tests/               단위 테스트
```
