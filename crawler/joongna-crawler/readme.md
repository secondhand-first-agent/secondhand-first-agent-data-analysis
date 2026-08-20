# 중고나라 크롤러 문서

## 1. 개요

`joongna_crawler.py`는 중고나라에서 사용자가 입력한 상품을 검색하고, 검색 페이지와 상세 페이지에 공개된 데이터를 JSON으로 저장한다.

실행 방식은 번개장터 크롤러와 동일하지만 데이터 구조는 중고나라 원본 의미를 우선한다.

- 검색어, 정렬 방식, 수집 개수, 최대 페이지, 요청 간격, 출력 경로를 실행 인자로 받는다.
- 판매 중인 일반 상품만 수집한다.
- 중복, 부품, 구매, 대여 글을 제외한다.
- 검색 페이지의 Next.js 상품 데이터와 상세 페이지의 JSON-LD를 분리해 보존한다.
- 플랫폼 간 의미가 확실히 같은 최소 데이터만 `common`에 저장한다.
- 중고나라 전용 필드는 이름이나 의미를 바꾸지 않고 `joongna` 아래에 저장한다.
- 중고나라 필드를 번개장터 필드에 억지로 대응시키거나 미제공 값을 `0`, `false`로 채우지 않는다.

> 이 크롤러는 중고나라 웹에서 공개적으로 조회되는 페이지와 구조화 데이터를 사용한다. 사이트 구조가 변경되면 코드 수정이 필요할 수 있으며, 서비스에 부담을 주지 않도록 낮은 요청 빈도로 사용해야 한다.

## 2. 파일 구성

```text
joongna-crawler/
├── joongna_crawler.py
├── readme.md
└── output/
    └── joongna_에어팟_프로3.json
```

저장소 루트의 `.venv`를 공용 가상환경으로 사용하며 가상환경 자체는 Git에 저장하지 않는다. 크롤러는 Python 3.10 이상에서 외부 패키지 없이 실행된다.

## 3. 실행 방법

다음 명령은 `joongna-crawler` 폴더에서 실행하는 것을 기준으로 한다.

```bash
# 에어팟 프로3, 최신순, 기본 20개
python3 joongna_crawler.py "에어팟 프로3"

# 아이폰 15 프로, 추천순, 기본 20개
python3 joongna_crawler.py "아이폰 15 프로" --sort score

# 닌텐도 스위치 OLED, 최신순, 10개
python3 joongna_crawler.py "닌텐도 스위치 OLED" \
  --sort latest \
  --limit 10

# 루트 공용 가상환경으로 에어팟 프로3 5개 수집
../../.venv/bin/python joongna_crawler.py "에어팟 프로3" \
  --sort latest \
  --limit 5
```

### 실행 옵션

| 인자 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `query` | 예 | 없음 | 검색할 상품명 |
| `--sort` | 아니요 | `latest` | `latest`는 최신순, `score`는 중고나라 추천순 |
| `--limit` | 아니요 | `20` | 수집할 정상 상품 수. 1 이상이어야 함 |
| `--max-pages` | 아니요 | `10` | 확인할 최대 검색 페이지 수. 1 이상이어야 함 |
| `--delay` | 아니요 | `1.0` | 요청 사이 대기 시간(초). 0 이상이어야 함 |
| `--output` | 아니요 | 자동 생성 | 결과 JSON을 저장할 경로 |

정렬값은 다음과 같이 중고나라 값으로 변환한다.

| CLI 값 | 중고나라 값 | 의미 |
| --- | --- | --- |
| `latest` | `RECENT_SORT` | 최신순 |
| `score` | `RECOMMEND_SORT` | 추천순 |

`--output`을 생략하면 현재 작업 디렉터리를 기준으로 `output/joongna_{검색어}.json`에 저장한다.

## 4. 수집 및 필터링 과정

1. 검색어, 중고나라 정렬값, 페이지 번호를 포함해 `/search/{query}`를 요청한다.
2. 검색 페이지의 Next.js 데이터에서 상품 객체를 원래 필드명으로 추출한다.
3. `seq`를 기준으로 중복을 제거한다.
4. `state=0`, `objectType=product`인 결과만 사용한다.
5. 제목을 정규화해 검색어 일치 여부를 검사한다.
6. 검색어에는 없지만 제목에 유닛·본체·케이스·부품·매입·구매·대여 표현이 있으면 제외한다.
7. `/product/{product_id}`의 JSON-LD에서 `Product`와 `BreadcrumbList`를 추출한다.
8. 상세 제목을 다시 검사한 후 정상 상품이 `--limit`에 도달하면 종료한다.

영문과 한글 상품명 비교를 위해 `AirPods → 에어팟`, `iPhone → 아이폰`, `Pro → 프로` 등 최소 별칭만 적용한다. 이 정규화는 필터링에만 사용하며 저장되는 원본 제목은 바꾸지 않는다.

## 5. 데이터 구조 설계 원칙

상품 하나는 세 영역으로 나뉜다.

```json
{
  "platform": "JOONGNA",
  "platformProductId": "231676347",
  "url": "https://web.joongna.com/product/231676347",
  "common": {
    "title": "에어팟 프로3 풀박스",
    "description": "상품 설명",
    "price": 160000,
    "currency": "KRW",
    "images": []
  },
  "joongna": {
    "search": {},
    "detail": {
      "jsonLdProduct": {},
      "jsonLdBreadcrumb": []
    }
  }
}
```

### 공통 식별 영역

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `platform` | string | 플랫폼 식별자. 항상 `JOONGNA` |
| `platformProductId` | string | 중고나라 검색 필드 `seq`를 문자열로 표현한 값 |
| `url` | string | 상품 ID로 구성한 중고나라 상세 페이지 URL |

### `common` 영역

플랫폼이 달라도 의미가 명확하게 같은 최소 필드만 저장한다.

| 필드 | 타입 | 출처 | 설명 |
| --- | --- | --- | --- |
| `title` | string | JSON-LD `Product.name`, 없으면 검색 `title` | 상품명 |
| `description` | string \| null | JSON-LD `Product.description` | 전화번호와 이메일을 마스킹한 설명 |
| `price` | number \| null | JSON-LD `offers.price`, 없으면 검색 `price` | 현재 표시 가격 |
| `currency` | string \| null | JSON-LD `offers.priceCurrency` | 가격 통화 |
| `images` | array[string] | JSON-LD `Product.image` | 상품 이미지 URL 목록 |

상태, 배송, 픽업, 판매자 등 플랫폼마다 정의가 다른 데이터는 `common`에 넣지 않는다.

### `joongna` 영역

중고나라 원본 의미를 유지해야 하는 데이터만 저장한다.

- `joongna.search`: 검색 페이지에 포함된 중고나라 상품 객체
- `joongna.detail.jsonLdProduct`: 상세 페이지의 `Product` JSON-LD 객체
- `joongna.detail.jsonLdBreadcrumb`: 상세 페이지의 `BreadcrumbList.itemListElement`
- `joongna.detail.condition`: 상세 페이지 내부 데이터의 `condition` 객체
- `joongna.detail.tradeType`: 상세 페이지 내부 데이터의 `tradeType` 객체
- `joongna.detail.deliveryInfos`: 상세 페이지 내부 데이터의 `deliveryInfos` 배열

`parcelFee`를 `freeShipping`으로, `pickupBadgeFlag`를 `inPersonTrade`로 변환하지 않는다. JSON-LD의 `itemCondition`도 별도 상태 코드로 재해석하지 않고 중고나라 상세 데이터 그대로 저장한다.

### JSON-LD로 알 수 없는 필드

JSON-LD의 `offers.itemCondition`은 미개봉 상품까지 포함해 표본 22건 전부 `UsedCondition`으로 고정되어 있어 실제 상태를 반영하지 못한다. 거래방식과 실제 배송비도 JSON-LD에 없다.

이 세 값은 상세 페이지에 함께 실려 있는 중고나라 내부 데이터에서 원본 형태 그대로 읽어 저장한다. 원본에서 읽지 못하면 키를 만들지 않는다.

```json
{
  "condition": {
    "productCondition": 0,
    "options": { "fullPackageYn": 0, "limitedEditionYn": 0, "flawedYn": 0 }
  },
  "tradeType": { "isPost": true, "isMeet": false, "isPickup": false },
  "deliveryInfos": [{ "deliveryType": 0, "deliveryPrice": 4000 }]
}
```

값의 의미는 해석하지 않고 그대로 둔다. 해석은 통합 스키마 변환 단계에서 한다.

## 6. 최상위 결과 구조

출력 파일은 실행 정보, 상품 배열, 오류 배열로 구성된다.

```json
{
  "query": "에어팟 프로3",
  "sort": "latest",
  "requestedCount": 5,
  "collectedAt": "2026-08-19T07:23:33.765621+00:00",
  "count": 5,
  "failedCount": 0,
  "products": [],
  "errors": []
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `query` | string | 실행 시 입력한 검색어 |
| `sort` | string | CLI 정렬값 `latest` 또는 `score` |
| `requestedCount` | number | 요청한 정상 상품 수 |
| `collectedAt` | string | UTC 기준 ISO 8601 수집 완료 시각 |
| `count` | number | 실제 저장한 상품 수 |
| `failedCount` | number | 상세 조회 실패 수 |
| `products` | array | 상품 객체 배열 |
| `errors` | array | 상세 조회 오류 배열 |

이 최상위 필드는 플랫폼 원본 상품 데이터가 아니라 크롤러 실행 메타데이터다.

## 7. `joongna.search` 원본 필드

아래 필드는 실제 수집 결과에서 확인된 Next.js 검색 상품 필드다. 값은 별도 의미 변환 없이 저장한다.

| 필드 | 확인된 타입 | 설명 |
| --- | --- | --- |
| `seq` | number | 중고나라 상품 ID |
| `productPositionNo` | number | 현재 검색 결과 내 상품 위치 번호 |
| `platformType` | number | 중고나라 원본 플랫폼 유형 값 |
| `price` | number | 검색 결과 표시 가격 |
| `parcelFee` | number | 중고나라 배송 관련 원본 표시값. 불리언으로 해석하지 않음 |
| `url` | string | 검색 결과 썸네일 이미지 URL |
| `title` | string | 검색 결과 상품명 |
| `state` | number | 중고나라 상품 상태 원본값. 크롤러는 `0`만 수집 |
| `sortDate` | string | 검색 정렬에 사용하는 원본 날짜 문자열 |
| `mainLocationName` | string \| null | 대표 지역명 |
| `articleSeq` | number | 중고나라 원본 게시글 번호 값 |
| `articleUrl` | string \| null | 중고나라 원본 게시글 URL 값 |
| `videoProductYn` | string | 동영상 상품 여부 원본값 |
| `wishCount` | number | 관심 수 |
| `jnPayBadgeFlag` | boolean | 중고나라 안심결제 배지 원본값 |
| `pickupBadgeFlag` | boolean | 중고나라 픽업 배지 원본값 |
| `highlightedTitle` | string | 검색 강조 제목 원본값 |
| `chatCount` | number | 채팅 수 |
| `selfAuditFlag` | boolean | 중고나라 자체 검수 관련 원본값 |
| `userType` | number | 중고나라 사용자 유형 원본값 |
| `certifySellerFlag` | boolean | 인증 판매자 표시 원본값 |
| `locationNames` | array[string] | 공개 지역명 목록 |
| `objectType` | string | 검색 객체 유형. 크롤러는 `product`만 수집 |
| `wishYn` | number | 현재 검색 응답의 관심 여부 원본값 |

필드 이름만으로 의미를 확정하기 어려운 값은 추론하지 않고 “원본값”으로 기록한다.

## 8. `joongna.detail` 원본 필드

### `jsonLdProduct`

상세 페이지의 schema.org `Product` 객체를 구조 그대로 저장한다.

| 필드 | 확인된 타입 | 설명 |
| --- | --- | --- |
| `@type` | string | JSON-LD 유형. `Product` |
| `name` | string | 상세 상품명 |
| `image` | array[string] | 상세 상품 이미지 목록 |
| `description` | string | 전화번호와 이메일만 마스킹한 상세 설명 |
| `sku` | string | JSON-LD 상품 식별값 |
| `offers` | object | 가격, 통화, 상태, 재고, URL, 판매자 정보 |

실제 `offers`에는 다음과 같은 schema.org 필드가 포함될 수 있다.

| 필드 | 설명 |
| --- | --- |
| `price` | 상세 페이지 표시 가격 |
| `priceCurrency` | 통화 코드 |
| `itemCondition` | schema.org 상품 상태 URL |
| `availability` | schema.org 재고 상태 URL |
| `url` | 상세 상품 URL |
| `seller` | `@type`, `name`을 포함한 공개 판매자 객체 |

### `jsonLdBreadcrumb`

상세 페이지의 `BreadcrumbList.itemListElement`를 배열 그대로 저장한다. 각 항목에는 다음 필드가 포함될 수 있다.

| 필드 | 설명 |
| --- | --- |
| `@type` | JSON-LD 유형. `ListItem` |
| `position` | 카테고리 경로 내 순서 |
| `name` | 홈, 카테고리 또는 상품명 |
| `item` | 해당 경로 URL. 마지막 상품 항목에는 없을 수 있음 |

## 9. 저장하지 않거나 변환하지 않는 데이터

### 개인정보 보호를 위해 저장하지 않는 값

- 검색 데이터의 판매자 내부 ID `storeSeq`
- 설명에 포함된 전화번호
- 설명에 포함된 이메일

전화번호와 이메일은 `common.description`과 `jsonLdProduct.description` 모두에서 마스킹한다.

### 의미 충돌 방지를 위해 만들지 않는 필드

- `freeShipping`: 중고나라 `parcelFee`의 의미를 번개장터 값과 동일하다고 단정하지 않음
- `inPersonTrade`: `pickupBadgeFlag`를 직거래 가능 여부로 바꾸지 않음
- `condition`, `conditionLabel`: 제목에서 상품 상태를 추론하지 않음
- `originalPrice`: 검색 가격을 원래 가격으로 재정의하지 않음
- `createdAt`, `updatedAt`: `sortDate`를 등록·수정 시각으로 단정하지 않음
- `viewCount`, `commentCount`: 미제공 값을 `0`으로 채우지 않음
- 판매자 평점·리뷰·판매 수·프로상점 여부: 미제공 기본값을 만들지 않음

## 10. 실제 수집 결과

2026-08-19에 다음 명령으로 원본 보존형 구조를 검증했다.

```bash
../../.venv/bin/python joongna_crawler.py "에어팟 프로3" \
  --sort latest \
  --limit 5
```

| 항목 | 결과 |
| --- | --- |
| 요청 상품 수 | 5개 |
| 저장 상품 수 | 5개 |
| 상세 조회 실패 | 0개 |
| 검색 1페이지에서 확인한 결과 | 50개 |
| 저장 상품 가격 범위 | 160,000원~285,000원 |

실제 결과에서 상품별로 다음 구조를 확인했다.

- 공통 식별 필드: `platform`, `platformProductId`, `url`
- 최소 공통 필드: `title`, `description`, `price`, `currency`, `images`
- 중고나라 검색 원본 필드: 24개
- 상세 원본: `jsonLdProduct`, `jsonLdBreadcrumb`
- 판매자 내부 ID, 전화번호, 이메일: 저장되지 않음

판매 상품과 가격은 실행 시점에 따라 달라진다.

## 11. 오류 처리

검색과 상세 페이지 요청의 타임아웃은 20초이며 네트워크, HTTP, 타임아웃, 문자 디코딩 오류는 최대 3회 재시도한다. 개별 상세 조회가 최종 실패하면 전체 수집을 중단하지 않고 다음 형식으로 `errors`에 기록한다.

```json
{
  "productId": "상품 ID",
  "reason": "오류 내용"
}
```

## 12. 향후 공통 스키마 설계 기준

다른 플랫폼도 같은 방식으로 먼저 조사한다.

1. 크롤러 CLI와 실행 메타데이터는 동일하게 유지한다.
2. 플랫폼 원본 필드는 플랫폼 이름 아래에 보존한다.
3. 의미가 확실히 같은 최소 데이터만 `common`에 추가한다.
4. 비슷해 보이지만 정의가 다른 값은 변환하지 않는다.
5. 값이 없는 경우 임의의 `0`, `false`, 복사값을 만들지 않는다.
6. 모든 플랫폼의 원본 필드를 확인한 뒤 최종 공통 스키마를 확정한다.
