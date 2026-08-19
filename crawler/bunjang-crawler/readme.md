# 번개장터 크롤러

## 1. 개요

`bunjang_crawler.py`는 번개장터 판매 상품을 검색하고 상세 정보를 조회해 JSON으로 저장한다.

다른 플랫폼과 필드 의미가 섞이지 않도록 상품 객체를 다음 두 영역으로 나눈다.

- `common`: 세 플랫폼에서 의미가 확실히 같은 최소 필드
- `bunjang`: 번개장터의 원본 필드명과 중첩 구조를 유지한 검색·상세 데이터

공통 필드로 추측해서 변환할 수 없는 상태, 거래, 통계, 판매자, 카테고리 정보는 모두 `bunjang` 아래에만 둔다. 원본에 없는 불리언이나 숫자를 `false`, `0`으로 만들어 저장하지 않는다.

> 번개장터 웹에서 공개적으로 조회되는 내부 데이터 경로를 사용하므로 사이트 변경 시 수정이 필요할 수 있다. 서비스에 부담을 주지 않도록 낮은 요청 빈도로 사용한다.

## 2. 파일 구성

```text
bunjang-crawler/
├── bunjang_crawler.py
├── readme.md
└── output/
    └── bunjang_에어팟_프로3.json
```

## 3. 실행 방법

Python 3.10 이상이 필요하며 외부 패키지는 사용하지 않는다. 아래 명령은 `bunjang-crawler` 폴더에서 실행한다.

```bash
# 에어팟 프로3 최신순 5개
python3 bunjang_crawler.py "에어팟 프로3" --sort latest --limit 5

# 아이폰 15 프로 정확도순 20개
python3 bunjang_crawler.py "아이폰 15 프로" --sort score --limit 20

# 닌텐도 스위치 OLED 최신순 10개
python3 bunjang_crawler.py "닌텐도 스위치 OLED" \
  --sort latest \
  --limit 10
```

| 인자 | 기본값 | 설명 |
| --- | --- | --- |
| `query` | 없음 | 검색할 상품명 |
| `--sort` | `latest` | `latest`는 번개장터 최신순, `score`는 번개장터 정확도순 |
| `--limit` | `20` | 저장할 정상 상품 수 |
| `--max-pages` | `10` | 확인할 최대 검색 페이지 수 |
| `--delay` | `1.0` | 요청 사이 대기 시간(초) |
| `--output` | 자동 생성 | 결과 JSON 경로 |

출력 경로를 생략하면 현재 실행 위치를 기준으로 `output/bunjang_{검색어}.json`에 저장한다.

## 4. 수집 및 필터링

1. 검색 API를 `latest` 또는 `score`로 호출한다.
2. 외부 광고, 번개장터 검색 광고, 중복 상품, 판매 완료 상품을 제외한다.
3. 검색어와 제목이 일치하지 않거나 부품·구매·대여 글이면 제외한다.
4. 상세 API를 호출하고 상세 제목과 판매 상태를 다시 확인한다.
5. 공통 필드와 개인정보를 제거한 번개장터 원본 데이터를 저장한다.

| 용도 | 데이터 경로 |
| --- | --- |
| 상품 검색 | `/api/search/v8/web/search` |
| 상품 상세 | `/api/pms/v1/products/{product_id}/detail/web` |

설명의 전화번호와 이메일은 마스킹하며, 검색·상세 응답의 판매자 내부 `uid`와 상세 응답의 정확한 위도·경도는 제거한다. 검색 요청마다 바뀌며 상품 분석에 필요하지 않은 `tracking`도 저장하지 않는다. 판매자 표시 이름, 공개 지역명, 통계, 카테고리 ID처럼 번개장터가 공개한 비식별 필드는 원래 위치에 보존한다.

## 5. JSON 구조

```json
{
  "query": "에어팟 프로3",
  "sort": "latest",
  "requestedCount": 5,
  "collectedAt": "2026-08-19T00:00:00+00:00",
  "count": 5,
  "failedCount": 0,
  "products": [
    {
      "platform": "BUNJANG",
      "platformProductId": "상품 ID",
      "url": "번개장터 상품 URL",
      "common": {
        "title": "상품 제목",
        "description": "개인정보를 마스킹한 설명",
        "price": 250000,
        "currency": "KRW",
        "images": []
      },
      "bunjang": {
        "search": {},
        "detail": {}
      }
    }
  ],
  "errors": []
}
```

### 최상위 필드

| 필드 | 설명 |
| --- | --- |
| `query` | 입력한 검색어 |
| `sort` | 사용자가 요청한 번개장터 정렬 인자 |
| `requestedCount` | 요청한 정상 상품 수 |
| `collectedAt` | 수집 완료 시각(UTC ISO 8601) |
| `count` | 실제 저장된 상품 수 |
| `failedCount` | 상세 조회 실패 수 |
| `products` | 상품 객체 배열 |
| `errors` | 실패한 상품 ID와 오류 내용 |

### 상품 공통 필드

`common`에는 현재 세 플랫폼에서 의미가 확실한 값만 둔다.

| 필드 | 번개장터 출처 | 설명 |
| --- | --- | --- |
| `title` | `bunjang.detail.product.name` | 상품 게시글 제목 |
| `description` | `bunjang.detail.product.description` | 개인정보 마스킹이 적용된 설명 |
| `price` | `bunjang.detail.product.price` | 현재 판매 가격 |
| `currency` | 코드에서 지정 | 통화 `KRW` |
| `images` | `imageUrl`, `imageCount` | 원본 템플릿으로 생성한 상세 이미지 URL |

`platform`, `platformProductId`, `url`은 상품 출처와 플랫폼 내부 식별을 위한 공통 메타데이터다.

### 번개장터 전용 필드

- `bunjang.search`: 검색 결과의 상품 객체를 원본 필드명으로 보존한다.
- `bunjang.detail`: 상세 응답의 `data` 객체를 원본 중첩 구조로 보존한다.

주요 원본 경로는 다음과 같다. 아래 필드는 공통 의미가 확정되지 않았으므로 이름을 바꾸지 않는다.

| 의미 범주 | 번개장터 원본 경로 예시 |
| --- | --- |
| 판매 상태 | `bunjang.search.status`, `bunjang.detail.product.saleStatus` |
| 상품 상태 | `bunjang.detail.product.condition`, `bunjang.detail.productSpecs` |
| 거래 방식 | `bunjang.detail.product.trade`, `bunjang.detail.bunpay` |
| 관심·채팅·조회 | `bunjang.search.favoriteCount`, `buntalkCount`, `bunjang.detail.product.metrics` |
| 카테고리·브랜드 | `bunjang.detail.product.category`, `categories`, `brand` |
| 판매자 공개 정보 | `bunjang.detail.shop` |
| 등록·수정 시각 | `bunjang.detail.product.describedAt`, `updatedAt` |

같은 이름처럼 보이더라도 다른 플랫폼의 상태·배송·관심·채팅 값과 집계 기준이 같다고 확인되기 전에는 공통 필드로 승격하지 않는다.

## 6. 원본 보존 예외

다음 값은 안전과 재현성을 위해 원본 그대로 저장하지 않는다.

- 상품 설명의 전화번호와 이메일: 마스킹
- `bunjang.search.shop.uid`, `bunjang.detail.shop.uid`: 제거
- `bunjang.detail.product.geo.lat`, `lon`: 정확한 좌표이므로 제거
- `bunjang.search.tracking`: 요청별 추적 데이터이므로 제거
- 원본에 없는 값: 임의의 `false`, `0`, 빈 문자열을 생성하지 않음

이미지 원본 템플릿이 없으면 공통 `images`는 빈 배열이지만, 원본 필드의 존재 여부는 `bunjang.detail.product`에서 따로 확인할 수 있다.

## 7. 오류 처리

- 요청 타임아웃은 20초이며 HTTP·네트워크·JSON 오류를 최대 3회 재시도한다.
- 한 상품의 상세 조회가 실패해도 다음 상품을 계속 수집한다.
- 요청 개수보다 적게 수집되면 실제 개수를 `count`에 기록한다.
