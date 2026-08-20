# Apple 공식 홈페이지 Playwright 크롤러 문서

## 1. 개요

`crawler.py`는 Apple 공식 홈페이지에서 특정 상품 페이지를 크롤링하고, 페이지에 공개된 상품 데이터를 JSON으로 저장한다.

> **통합 크롤러에서는 제외했다.** `run_unified_crawl.py`가 돌리는 것은
> 번개장터·중고나라·N플리마켓·11번가 네 개다.
>
> Apple 공식 홈페이지는 **Apple 제품만** 다루므로 임의의 검색어를 받는 통합 파이프라인에
> 넣을 수 없다. 사용자가 "책상"이나 "자전거"를 찾을 때 이 크롤러는 아무것도 돌려주지 못한다.
> 새상품 비교 기준은 전 품목을 다루는 11번가가 맡는다.
>
> 실행 방식도 다르다. Playwright가 필요하고(나머지 넷은 표준 라이브러리만 쓴다),
> 검색어를 받는 실행 인자가 없으며, 출력 구조도 `common`/`{platform}` 규약을 따르지 않는다.
> Apple 제품에 한정한 시세 확인 용도로 따로 실행한다.

번개장터·중고나라·N플리마켓 크롤러와 달리 **Playwright**를 사용해 실제 브라우저를 제어하는 방식으로 동작한다. Apple 공식 페이지는 JavaScript로 렌더링되는 동적 콘텐츠를 포함하고 있어, 단순 HTTP 요청 방식으로는 완전한 데이터 수집이 어렵기 때문이다.

- 수집 대상 URL을 직접 지정해 특정 상품 페이지를 크롤링한다.
- 제품명, 가격, 설명, 제품 구성, 주요 기능, 방수 등급, 배터리, FAQ, 비교 모델 정보를 수집한다.
- 수집 결과를 JSON 파일로 저장한다.
- 각주 기호(`각주 ¹²³...`)는 정규식으로 정제해 저장하지 않는다.

> 이 크롤러는 Apple 공식 홈페이지에서 공개적으로 조회되는 페이지를 사용한다. 사이트 구조가 변경되면 CSS 셀렉터 수정이 필요할 수 있으며, 서비스에 부담을 주지 않도록 낮은 요청 빈도로 사용해야 한다.

---

## 2. 파일 구성

```text
apple-crawler/
├── venv/                   ← Python 가상환경 (Git에 저장하지 않음)
├── crawler.py              ← 크롤러 본체
├── readme.md
└── airpods_pro3.json       ← 수집 결과 JSON (실행 후 생성)
```

---

## 3. 의존성 및 환경 설정

Python 3.8 이상이 필요하며, 외부 패키지로 **Playwright**를 사용한다.

```bash
# 1. 프로젝트 폴더 생성
mkdir apple-crawler && cd apple-crawler

# 2. 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate       # macOS / Linux
# venv\Scripts\activate        # Windows

# 3. Playwright 설치
pip install playwright

# 4. 브라우저 바이너리 설치 (Chromium, Firefox, WebKit)
playwright install

# 5. 설치 확인
python3 -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"
```

| 패키지 | 역할 |
| --- | --- |
| `playwright` | 브라우저 자동화 및 DOM 조작 |
| `json` | 결과 JSON 직렬화 (표준 라이브러리) |
| `re` | 각주 기호 정규식 제거 (표준 라이브러리) |
| `datetime` | 수집 시각 기록 (표준 라이브러리) |

---

## 4. 실행 방법

```bash
# 가상환경 활성화 후 실행
source venv/bin/activate
python3 crawler.py
```

실행하면 터미널에 진행 상황이 출력되고, 완료 시 `airpods_pro3.json`이 생성된다.

```
🔍 페이지 로딩 중... https://www.apple.com/kr/shop/buy-airpods/airpods-pro-3
✅ 크롤링 완료! → airpods_pro3.json
  제품명: AirPods Pro 3 구입하기
  가격:   ₩369,000
  방수:   IP57
  배터리: 8시간 (ANC)
  주요기능 N개, 제품구성 N개 수집
```

---

## 5. 수집 항목 및 추출 방식

| 필드 | 추출 방식 | 설명 |
| --- | --- | --- |
| `product_name` | `h1` 태그 텍스트 | 페이지 상품명 |
| `price` | `a[href*='step=select']` 링크 텍스트 | 판매 가격 |
| `description` | `h1` 인접 `p` 태그 | 상품 소개 문구 |
| `in_the_box` | `ul li` 전체 순회 후 키워드 필터 | 제품 구성 목록 |
| `key_features` | `ul li` 전체 순회 후 키워드 필터 | 주요 기능 문구 |
| `battery_anc_hours` | `key_features` 문자열에서 정규식 추출 | ANC 기준 배터리 시간(정수) |
| `water_resistance` | `key_features` 문자열에서 정규식 추출 | 방수 등급 (예: IP57) |
| `faq` | `h3` 태그 텍스트 중 질문형 필터 | 자주 묻는 질문 목록 |
| `compare_models` | `h3 a` 앵커 텍스트 및 href | 비교 모델명 및 링크 |
| `url` | 코드에서 고정값 지정 | 수집 대상 URL |
| `crawled_at` | `datetime.now().isoformat()` | 수집 시각 |

### 텍스트 정제 규칙

원본 페이지에는 `각주 ¹`, `각주 ²³` 등의 각주 표시가 포함되어 있다. 이를 아래 정규식으로 제거한 후 저장한다.

```python
re.sub(r'\s*각주\s*[\^¹²³⁴⁵⁶⁷⁸⁹⁰]+', '', text).strip()
```

---

## 6. 결과 JSON 구조

```json
{
  "url": "https://www.apple.com/kr/shop/buy-airpods/airpods-pro-3",
  "crawled_at": "2026-08-19T19:00:00.000000",
  "product_name": "AirPods Pro 3 구입하기",
  "price": "₩369,000",
  "description": "이제 세계 최고의 인이어 액티브 노이즈 캔슬링...",
  "overview": [],
  "in_the_box": [
    "AirPods Pro 3",
    "스피커 및 랜야드 루프를 갖춘 MagSafe 충전 케이스(USB-C)",
    "실리콘 이어팁(다섯 가지 크기: XXS, XS, S, M, L)",
    "설명서"
  ],
  "key_features": [
    "최초 AirPods Pro 및 AirPods 4 액티브 노이즈 캔슬링 모델 대비 최대 4배 강력한 액티브 노이즈 캔슬링",
    "운동 중 심박수 측정 기능",
    "한 번 충전 시 액티브 노이즈 캔슬링 상태로 최대 8시간 청취 가능",
    "MagSafe 충전 케이스(USB-C)",
    "IP57 등급 방진 및 방수"
  ],
  "battery_anc_hours": 8,
  "water_resistance": "IP57",
  "faq": [
    { "question": "청각 건강 기능은 어디에서 이용할 수 있는지?" },
    { "question": "실시간 번역 기능은 어떤 언어로 지원되는지?" }
  ],
  "compare_models": [
    { "name": "AirPods 4", "url": "https://..." },
    { "name": "AirPods Pro 3", "url": "https://..." },
    { "name": "AirPods Max 2", "url": "https://..." }
  ]
}
```

### 최상위 필드 설명

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `url` | string | 수집한 상품 페이지 URL |
| `crawled_at` | string | ISO 8601 형식 수집 시각 |
| `product_name` | string \| null | 상품명 |
| `price` | string \| null | 가격 문자열 (통화 기호 포함) |
| `description` | string \| null | 상품 소개 문구 |
| `overview` | array[string] | 상세 설명 문단 목록 |
| `in_the_box` | array[string] | 제품 구성 목록 |
| `key_features` | array[string] | 주요 기능 문구 목록 (최대 15개) |
| `battery_anc_hours` | number \| null | ANC 기준 배터리 시간(정수) |
| `water_resistance` | string \| null | 방수 등급 코드 (예: IP57) |
| `faq` | array[object] | 자주 묻는 질문 목록 |
| `compare_models` | array[object] | 비교 모델명 및 URL |

---

## 7. Playwright 동작 원리와 기존 HTTP 방식과의 차이

### 7-1. 기존 HTTP 요청 방식 (번개장터·중고나라·N플리마켓 크롤러)

팀원들의 크롤러는 Python 표준 라이브러리만으로 동작한다. 내부적으로 다음 흐름을 따른다.

```
Python 코드
  └─ urllib / http.client (TCP 소켓)
       └─ HTTP GET 요청 전송
            └─ 서버 응답 수신 (HTML 또는 JSON)
                 └─ JSON.parse() 또는 HTML 파싱
                      └─ 데이터 추출
```

이 방식이 통한 이유는 세 플랫폼 모두 **검색 API와 상세 API가 분리되어 공개**되어 있고, 응답이 JSON 형태로 바로 반환되기 때문이다. 브라우저 없이도 API 엔드포인트에 직접 요청하면 원하는 데이터를 받을 수 있었다.

```
# 번개장터 예시
GET /api/search/v8/web/search?query=에어팟+프로3
→ 응답: {"data": {"list": [{"product_id": ..., "price": ...}]}}
```

### 7-2. Playwright 방식 (Apple 크롤러)

Apple 공식 홈페이지는 위와 같은 공개 JSON API가 존재하지 않는다. 페이지 전체가 JavaScript로 렌더링되며, 서버는 **실제 브라우저인지 봇인지를 엄격하게 판별**한다. 이 문제를 Playwright가 해결한다.

```
Python 코드
  └─ Playwright
       └─ Chromium 브라우저 실제 실행 (headless 모드)
            └─ 브라우저가 직접 HTTP 요청
                 └─ JavaScript 실행 및 DOM 완전 렌더링
                      └─ Python이 DOM 쿼리로 데이터 추출
```

Playwright는 구글 Chrome 개발팀이 만든 **Chrome DevTools Protocol(CDP)** 위에서 동작한다. 실제 브라우저 프로세스를 띄우고, Python 코드가 그 브라우저를 원격으로 제어하는 구조다. 브라우저 입장에서는 사람이 직접 접속한 것과 동일하게 보인다.

### 7-3. 핵심 차이점 비교

| 항목 | HTTP 요청 방식 (팀원 크롤러) | Playwright 방식 (Apple 크롤러) |
| --- | --- | --- |
| **브라우저 실행** | 없음 (Python만 사용) | Chromium 실제 실행 |
| **JavaScript 실행** | 불가 | 가능 (브라우저가 처리) |
| **동적 콘텐츠 수집** | 불가 | 가능 (렌더링 완료 후 수집) |
| **외부 패키지** | 불필요 | `playwright` 필요 |
| **메모리 사용량** | 매우 낮음 | 높음 (브라우저 프로세스 포함) |
| **실행 속도** | 빠름 (수십 ms) | 느림 (브라우저 구동 포함, 수 초) |
| **봇 탐지 우회** | 어려움 | 상대적으로 용이 |
| **데이터 추출 방식** | JSON 직접 파싱 | DOM 쿼리 (`query_selector`) |
| **사이트 변경 영향** | API 구조 변경 시 수정 필요 | HTML 구조 변경 시 수정 필요 |
| **적합한 대상** | 공개 JSON API 제공 사이트 | 동적 렌더링·봇 차단 사이트 |

### 7-4. Apple에서 Playwright가 필요한 이유

Apple 공식 스토어 페이지가 단순 HTTP 요청으로 크롤링되지 않는 이유는 세 가지다.

첫째, **JavaScript 렌더링 의존**이다. 가격, 모델 옵션, 비교표 등 핵심 데이터가 HTML 초기 응답에 없고, 브라우저에서 JavaScript가 실행된 뒤에야 DOM에 삽입된다. Python만으로 요청하면 빈 껍데기 HTML만 받게 된다.

둘째, **봇 탐지 시스템**이다. Apple은 요청 헤더, TLS 핑거프린트, 쿠키, 동작 패턴 등을 종합해 봇 여부를 판단한다. 단순 `urllib` 요청은 즉시 차단되거나 다른 응답을 반환한다. Playwright는 실제 Chromium을 구동하므로 TLS 핑거프린트와 브라우저 동작이 실제 사용자와 동일하다.

셋째, **공개 API 부재**이다. 번개장터나 N플리마켓과 달리 Apple은 외부에서 직접 호출할 수 있는 상품 검색·상세 JSON API를 제공하지 않는다. 페이지 HTML과 DOM이 유일한 데이터 소스다.

---

## 8. 개인정보 및 데이터 처리

Apple 공식 페이지는 판매자 개인정보가 없는 공식 상품 정보만 포함하므로 별도 마스킹 처리는 적용하지 않는다. 단, 각주 기호는 분석에 불필요하므로 정규식으로 제거 후 저장한다.

---

## 9. 오류 처리 및 주의사항

- 페이지 로딩 타임아웃은 30초로 설정되어 있다. 네트워크 상태에 따라 실패할 수 있으며, 이 경우 재실행한다.
- Apple 사이트 HTML 구조가 변경되면 CSS 셀렉터를 수정해야 한다.
- `headless=False`로 변경하면 실제 브라우저 창이 열려 디버깅에 활용할 수 있다.
- 짧은 시간에 반복 요청 시 IP 차단 가능성이 있으므로 요청 간격을 충분히 유지한다.

---

## 10. 향후 확장 방향

1. `--url` 인자를 추가해 다른 Apple 상품 페이지도 수집할 수 있도록 일반화한다.
2. `--limit`, `--delay` 옵션을 추가해 여러 상품을 순차 수집하는 방식으로 확장한다.
3. 팀원 크롤러의 공통 스키마(`common`, 플랫폼 전용 영역)에 맞춰 출력 구조를 통일한다.
4. 수집 실패 시 `errors` 배열에 원인을 기록하는 오류 처리 구조를 추가한다.