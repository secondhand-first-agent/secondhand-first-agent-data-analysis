# 통합 크롤러

번개장터 / 중고나라 / N플리마켓 / 11번가 네 플랫폼을 한 번에 크롤링하고
통합 스키마로 합친다. 앞의 셋은 중고, 11번가는 새상품 비교 기준이다.

스키마 정의는 [`docs/통합_스키마_정의.md`](../../docs/통합_스키마_정의.md)를 참고한다.

## 1. 파일 구성

```text
crawler/unified/
├── run_unified_crawl.py            # 통합 실행기 — 크롤링부터 검증까지
├── transform_to_unified_schema.py  # 원본 3개 → 통합 스키마
├── validate_unified_schema.py      # 통합 결과 검증
├── readme.md
└── output/                         # 실행 결과
```

Python 3.10 이상이 필요하며 외부 패키지는 사용하지 않는다.

## 2. 빠른 시작

```bash
cd crawler/unified

# 상품 하나를 네 플랫폼에서 수집해 통합
python3 run_unified_crawl.py "닌텐도 스위치 OLED"

# 플랫폼당 10건씩 모으고 검증까지
python3 run_unified_crawl.py "냉장고" --limit 10 --validate
```

결과는 `output/unified_{검색어}.json`에 저장된다.

## 3. `run_unified_crawl.py`

네 크롤러를 차례로 실행하고 변환까지 이어서 돌린다.

| 인자 | 기본값 | 설명 |
| --- | --- | --- |
| `query` | 없음 | 검색할 상품명 |
| `--sort` | `latest` | `latest`=최신순, `score`=정확도순 |
| `--limit` | `3` | **플랫폼당** 수집할 상품 수 |
| `--delay` | `1.0` | 요청 사이 대기 시간(초) |
| `--outdir` | `unified/output` | 결과를 저장할 폴더 |
| `--keep-raw` | 끄기 | 플랫폼별 원본 JSON도 남긴다 |
| `--validate` | 끄기 | 변환 후 검증 스크립트까지 실행한다 |

`transform_to_unified_schema.py`의 `--elevenst`는 선택 인자다. 생략하면
중고 세 플랫폼만 변환한다.

### 원본 JSON도 남기기

기본적으로 플랫폼별 원본은 임시 폴더에 만들고 끝나면 지운다.
디버깅하려면 `--keep-raw`를 붙인다.

```bash
python3 run_unified_crawl.py "샤넬 가방" --keep-raw
# output/bunjang_샤넬_가방.json
# output/joongna_샤넬_가방.json
# output/naver_fleamarket_샤넬_가방.json
# output/elevenst_샤넬_가방.json
# output/unified_샤넬_가방.json
```

### 한 플랫폼이 0건이어도 계속 진행한다

플랫폼마다 검색 결과가 없는 상품군이 실제로 있다.
예를 들어 상품권류는 N플리마켓 검색 API가 0건을 반환한다.
크롤러가 실패하거나 0건이어도 나머지 결과로 변환을 이어간다.

```text
[수집 결과]
  bunjang             3건
  joongna             3건
  naver_fleamarket    0건
  elevenst            3건
```

### 요청 빈도

`--delay` 기본값 1초를 유지한다. 세 플랫폼 모두 공개 웹의 내부 데이터
경로를 사용하므로 짧은 시간에 반복 실행하지 않는다.

### 11번가 렌털은 자동으로 빠진다

11번가에는 렌털·구독 상품이 섞여 있고 상품상태가 `새상품`으로 나온다.
월 구독료가 판매가로 읽히면 총 지불액 비교가 깨지므로 기본적으로 제외한다.

```text
[제외] 렌털 상품: 9561407554 [구독/렌탈] (72개월약정) LG 베스트 정수기 가전구독…
[완료] 3개 수집
[렌털 제외] 1개
```

렌털까지 보려면 11번가 크롤러를 따로 실행하고 `--include-rental`을 붙인다.

## 4. 개별 스크립트

실행기를 거치지 않고 따로 쓸 수도 있다.

### 변환

```bash
python3 transform_to_unified_schema.py \
  --bunjang output/bunjang_냉장고.json \
  --joongna output/joongna_냉장고.json \
  --naver-fleamarket output/naver_fleamarket_냉장고.json \
  --elevenst output/elevenst_냉장고.json \
  --output output/unified_냉장고.json
```

### 검증

```bash
# 한 개
python3 validate_unified_schema.py output/unified_냉장고.json

# 여러 개 한 번에
python3 validate_unified_schema.py output/unified_*.json
```

오류가 하나라도 있으면 종료 코드 `1`을 반환한다.

## 5. 출력 형태

```jsonc
{
  "query": "닌텐도 스위치 OLED",
  "generatedAt": "2026-08-19T...",
  "sourceCounts": { "BUNJANG": 3, "JOONGNA": 3, "NAVER_FLEAMARKET": 3, "ELEVENST": 3 },
  "count": 9,
  "items": [ /* 통합 스키마 항목 */ ]
}
```

`items[]`의 각 필드는 [`docs/통합_스키마_정의.md`](../../docs/통합_스키마_정의.md)에 정리돼 있다.

## 6. 검증 리포트 읽는 법

```text
[BUNJANG] 3건
  condition_level: {'LIGHTLY_USED': 2, 'NEW': 1}
  trade_method 조합: {('MEET', 'PARCEL'): 2, ('MEET',): 1}
  delivery_fee.status: {'AVAILABLE': 3}
  delivery_fee.payer: {'SELLER': 1, 'BUYER': 2}
  배송 수단: {'FREE': 1, 'STANDARD': 2, 'CONVENIENCE_STORE': 2}
  편의점 픽업만 가능: 0/3
  location.precision: {'FULL': 3}
  거래 지역 2곳 이상: 0/3
```

눈여겨볼 항목은 두 가지다.

- **`편의점 픽업만 가능`** — 편의점 외 배송 수단이 없는 상품 수.
  픽업이 어려운 사용자에게는 사실상 구매 불가다. 경고로도 잡힌다.
- **`location.precision`** — `DONG_ONLY`나 `NONE`이 많으면 거리 점수를
  그대로 쓰면 안 된다. 플랫폼 간 형평성이 깨진다.

## 7. 문제가 생기면

| 증상 | 확인할 것 |
| --- | --- |
| 특정 플랫폼만 0건 | 검색어를 바꿔 본다. 플랫폼에 해당 카테고리가 없을 수 있다 |
| `condition_level`이 전부 `UNKNOWN` | 크롤러가 상태 필드를 수집하는 버전인지 확인한다 |
| 11번가에 렌털이 섞임 | `unitTxt`·상세 뱃지 판별을 통과한 것이다. 원본을 `--keep-raw`로 확인한다 |
| `delivery_fee.min_fee` 불일치 오류 | `options`와 대표 금액 계산이 어긋난 것이다. 변환 로직 버그다 |
| `location.precision`이 `DONG_ONLY` | N플리마켓 주소 조회가 실패했다. 네이버 지도 경로 변경 가능성 |
| 검증에서 `UNKNOWN` 배송 수단 | 새로운 원본 코드가 나온 것이다. 매핑 테이블에 추가가 필요하다 |
