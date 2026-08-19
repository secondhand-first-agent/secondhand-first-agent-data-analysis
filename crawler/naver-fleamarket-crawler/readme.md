# N플리마켓 크롤러 문서

## 1. 개요

`naver_fleamarket_crawler.py`는 N플리마켓에서 사용자가 입력한 상품을 검색하고, 검색 API와 상세 페이지에 공개된 상품 데이터를 JSON으로 저장한다.

실행 방식은 번개장터·중고나라 크롤러와 동일하지만 데이터 구조는 N플리마켓 원본 의미를 우선한다.

- 검색어, 정렬 방식, 수집 개수, 최대 페이지, 요청 간격, 출력 경로를 실행 인자로 받는다.
- 판매 중인 일반 상품만 수집한다.
- 검색어와 다른 상품, 부품, 구매, 대여 글을 제외한다.
- 검색 API 상품 객체와 상세 페이지의 Next.js 상품 상태 객체를 분리해 보존한다.
- 플랫폼 간 의미가 확실히 같은 최소 데이터만 `common`에 저장한다.
- N플리마켓 전용 필드는 이름이나 의미를 바꾸지 않고 `naverFleamarket` 아래에 저장한다.
- 배송비, 상품 상태, 결제 방식처럼 비슷해 보여도 플랫폼마다 의미가 달라질 수 있는 필드는 공통 필드로 합치지 않는다.

> 이 크롤러는 N플리마켓 웹에서 공개적으로 조회되는 페이지와 API를 사용한다. 사이트 구조가 변경되면 코드 수정이 필요할 수 있으며, 서비스에 부담을 주지 않도록 낮은 요청 빈도로 사용해야 한다.

## 2. 파일 구성

```text
naver-fleamarket-crawler/
├── naver_fleamarket_crawler.py
├── readme.md
└── output/
    └── naver_fleamarket_에어팟_프로3.json
```

저장소 루트의 `.venv`를 공용 가상환경으로 사용할 수 있으며 가상환경 자체는 Git에 저장하지 않는다. 크롤러는 Python 3.10 이상에서 외부 패키지 없이 실행된다.

## 3. 실행 방법

다음 명령은 `naver-fleamarket-crawler` 폴더에서 실행하는 것을 기준으로 한다.

```bash
# 에어팟 프로3, 최신순, 기본 20개
python3 naver_fleamarket_crawler.py "에어팟 프로3"

# 아이폰 15 프로, 관련도순, 기본 20개
python3 naver_fleamarket_crawler.py "아이폰 15 프로" --sort score

# 닌텐도 스위치 OLED, 최신순, 10개
python3 naver_fleamarket_crawler.py "닌텐도 스위치 OLED" \
  --sort latest \
  --limit 10

# 루트 공용 가상환경으로 에어팟 프로3 최신순 5개 수집
../../.venv/bin/python naver_fleamarket_crawler.py "에어팟 프로3" \
  --sort latest \
  --limit 5
```

### 실행 옵션

| 인자 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `query` | 예 | 없음 | 검색할 상품명 |
| `--sort` | 아니요 | `latest` | `latest`는 최신순, `score`는 관련도순 |
| `--limit` | 아니요 | `20` | 수집할 정상 상품 수. 1 이상이어야 함 |
| `--max-pages` | 아니요 | `10` | 확인할 최대 검색 페이지 수. 1 이상이어야 함 |
| `--delay` | 아니요 | `1.0` | 요청 사이 대기 시간(초). 0 이상이어야 함 |
| `--output` | 아니요 | 자동 생성 | 결과 JSON을 저장할 경로 |

CLI 정렬값은 N플리마켓 검색 API 값으로 다음과 같이 변환한다.

| CLI 값 | N플리마켓 값 | 의미 |
| --- | --- | --- |
| `latest` | `DATE_DESC` | 최신 등록순 |
| `score` | `REL_DESC` | 관련도순 |

`--output`을 생략하면 현재 작업 디렉터리를 기준으로 `output/naver_fleamarket_{검색어}.json`에 저장한다.

## 4. 수집 및 필터링 과정

1. 검색어, 시작 위치, 페이지 크기, 정렬값을 포함해 공개 검색 API를 요청한다.
2. `result.marketProducts`의 상품 객체를 원래 필드명으로 읽는다.
3. `marketProductId`를 기준으로 중복을 제거한다.
4. `saleStatus=ON_SALE`인 결과만 사용한다.
5. 제목을 정규화해 검색어 일치 여부를 검사한다.
6. 검색어에는 없지만 제목에 유닛·본체·케이스·부품·매입·구매·대여 표현이 있으면 제외한다.
7. `/market-products/{marketProductId}` 상세 페이지의 Next.js 공개 상태 데이터에서 상품 상세 객체를 추출한다.
8. 상세 제목을 다시 검사한 후 정상 상품이 `--limit`에 도달하면 종료한다.

영문과 한글 상품명 비교를 위해 `AirPods → 에어팟`, `iPhone → 아이폰`, `Pro → 프로` 등 최소 별칭만 필터링에 적용한다. 저장되는 원본 제목은 바꾸지 않는다.

## 5. 데이터 구조 설계 원칙

상품 하나는 공통 식별 영역, 최소 공통 필드, N플리마켓 원본 영역으로 나뉜다.

```json
{
  "platform": "NAVER_FLEAMARKET",
  "platformProductId": "01M0AJ53MD7HMTWK6J5HG62F9E",
  "url": "https://fleamarket.naver.com/market-products/01M0AJ53MD7HMTWK6J5HG62F9E",
  "common": {
    "title": "[A급/풀박스] 에어팟 프로3",
    "description": "...",
    "price": 250000,
    "currency": "KRW",
    "images": ["https://..."]
  },
  "naverFleamarket": {
    "search": {},
    "detail": {}
  }
}
```

### `common`에 포함한 필드

| 필드 | N플리마켓 원본 | 포함 이유 |
| --- | --- | --- |
| `title` | `detail.saleProduct.title` | 플랫폼 간 의미가 명확한 판매 글 제목 |
| `description` | `detail.saleProduct.content` | 플랫폼 간 의미가 명확한 판매 글 본문 |
| `price` | `detail.saleProduct.price` | 플랫폼 간 의미가 명확한 판매 가격 |
| `currency` | N플리마켓 원화 가격 | 가격 통화를 `KRW`로 명시 |
| `images` | `detail.saleProduct.productImages[].url` | 플랫폼 간 의미가 명확한 상품 이미지 |

이외의 값은 현재 단계에서 공통 스키마로 승격하지 않는다.

### 공통 필드로 합치지 않은 대표 항목

| N플리마켓 필드 | 유지 위치 | 이유 |
| --- | --- | --- |
| `productCondition` | `naverFleamarket.detail.saleProduct` | 상태 단계와 판정 기준이 플랫폼 전용 |
| `deliveryFeeInfo` | `naverFleamarket.search` | 화면 표시용 문자열이며 배송 정책 객체와 의미가 다름 |
| `saleProductDeliveries` | `naverFleamarket.detail.saleProduct` | 배송 유형·부담 주체·도서산간 요금 구조가 플랫폼 전용 |
| `saleProductRegions` | `naverFleamarket.detail.saleProduct` | N플리마켓의 지역 ID와 코드 체계 |
| `paymentType` | 검색·상세 원본 영역 | 안전거래 등 N플리마켓 거래 방식 값 |
| `hasNpayPurchaseHistory` | `naverFleamarket.search` | 네이버 구매 이력 기반 플랫폼 전용 값 |
| `isKept`, `keepCount` | 검색·상세 원본 영역 | 찜 여부와 찜 수를 나타내는 플랫폼 전용 값 |
| `commission` | `naverFleamarket.detail` | 조회 시점의 N플리마켓 구매자 보호 수수료 값 |
| `gdid` | `naverFleamarket.detail` | N플리마켓 응답의 상품 추적 식별 값 |

`deliveryFeeInfo`가 `무료배송`이라고 표시되더라도 별도의 공통 `freeShipping=true`를 만들지 않는다. 마찬가지로 `productCondition`을 다른 플랫폼 상태값에 임의 대응시키지 않는다.

## 6. 결과 JSON 최상위 필드

실제 `에어팟 프로3`, 최신순, 5개 실행 결과의 최상위 구조는 다음과 같다.

```json
{
  "query": "에어팟 프로3",
  "sort": "latest",
  "requestedCount": 5,
  "collectedAt": "2026-08-19T...+00:00",
  "count": 5,
  "failedCount": 0,
  "products": [],
  "errors": []
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `query` | string | 입력 검색어 |
| `sort` | string | CLI 정렬값 `latest` 또는 `score` |
| `requestedCount` | number | 요청한 정상 상품 수 |
| `collectedAt` | string | UTC 기준 ISO 8601 수집 시각 |
| `count` | number | 실제 저장 상품 수 |
| `failedCount` | number | 상세 조회 실패 수 |
| `products` | array | 수집된 상품 배열 |
| `errors` | array | 상세 조회에 실패한 상품 ID와 원인 |

## 7. `naverFleamarket.search` 원본 필드

5개 실제 결과에서 확인된 검색 상품 필드의 합집합이다. 상품에 따라 선택 필드가 없을 수 있다.

| 필드 | 확인된 타입 | 설명 |
| --- | --- | --- |
| `marketProductId` | string | N플리마켓 상품 ID |
| `title` | string | 판매 글 제목 |
| `productName` | string | 검색 응답의 별도 상품명 원본 필드 |
| `keepCount` | number | 찜 수 |
| `isKept` | boolean | 현재 요청 기준 찜 여부 |
| `saleStatus` | string | 판매 상태. 수집 결과에서는 `ON_SALE` |
| `price` | number | 판매 가격 |
| `productImageUrl` | string | 검색 카드 대표 이미지 URL |
| `hasNpayPurchaseHistory` | boolean | 네이버페이 구매 이력 관련 원본 플래그 |
| `paymentType` | string | N플리마켓 결제·거래 방식 값 |
| `deliveryFeeInfo` | string | 검색 카드의 배송비 표시 문자열. 선택 필드 |
| `createdAt` | number | 등록 시각 Unix epoch milliseconds |

## 8. `naverFleamarket.detail` 원본 필드

상세 페이지의 Next.js 상태 데이터에서 확인된 상품 객체를 보존한다.

### 상세 최상위

| 필드 | 설명 |
| --- | --- |
| `isKept` | 현재 요청 기준 찜 여부 |
| `keepCount` | 찜 수 |
| `isSeller` | 현재 요청자가 판매자인지 나타내는 원본 값 |
| `marketProductInfo` | 상품 ID, 시장 유형, 생성 시각, 교차 게시 정보 |
| `saleProduct` | 판매 글과 상품 상세 정보 |
| `commission` | 구매자 보호 수수료 관련 숫자 값 |
| `gdid` | 응답의 상품 추적 식별 값 |

### `marketProductInfo`

| 필드 | 설명 |
| --- | --- |
| `marketProductId` | N플리마켓 상품 ID |
| `marketType` | 상품이 속한 N플리마켓 시장 유형 |
| `createdAt` | 상세 응답의 상품 생성 시각 |
| `marketCrossPostedInfo` | 다른 마켓 교차 게시 관련 원본 객체 |

### `saleProduct`

| 필드 | 설명 |
| --- | --- |
| `title` | 판매 글 제목 |
| `productName` | 상세 응답의 별도 상품명 원본 필드 |
| `productCategoryId` | 최종 카테고리 ID |
| `productCategoryList` | 상위부터 하위까지의 카테고리 객체 배열 |
| `productCatalogId` | 연결된 상품 카탈로그 ID |
| `saleProductDeliveries` | 배송 유형, 배송비, 추가 배송비, 부담 주체 객체 배열 |
| `saleProductRegions` | 직거래 지역 ID, 이름, 지역 코드 객체 배열 |
| `hasCase` | 케이스 관련 N플리마켓 원본 플래그 |
| `hasWarranty` | 보증 관련 N플리마켓 원본 플래그 |
| `saleStatus` | 판매 상태 |
| `productCondition` | N플리마켓 상품 상태 코드 |
| `content` | 판매 글 본문. 전화번호와 이메일은 마스킹 |
| `price` | 판매 가격 |
| `useTransactionOffer` | 거래 제안 사용 여부 원본 플래그 |
| `brand` | 브랜드 원본 객체 |
| `productProperties` | 상품 속성 객체 배열 |
| `productImages` | 이미지 URL, 너비, 높이 객체 배열 |
| `paymentType` | 결제·거래 방식 값 |
| `lastModifiedAt` | 마지막 수정 시각 |

실제 결과에서 확인된 중첩 객체 필드는 다음과 같다.

- `productCategoryList[]`: `categoryId`, `name`, `parentCategoryId`, `depth`, `leaf`, `orderIndex`, `type`, `deleted`
- `saleProductDeliveries[]`: `deliveryType`, `deliveryFee`, `remoteDeliveryFee`, `payerType`
- `saleProductRegions[]`: `id`, `name`, `rcode`
- `productImages[]`: `url`, `width`, `height`

## 9. 개인정보 및 전송 데이터 처리

원본 필드를 최대한 보존하되 상품 분석에 불필요한 식별 정보와 전송 표기는 저장하지 않는다.

- `marketProductInfo.sellerProfileId`: 판매자 내부 식별자이므로 제거
- 본문 전화번호: `[전화번호 제거]`로 치환
- 본문 이메일: `[이메일 제거]`로 치환
- `$undefined`: React 서버 컴포넌트 전송 표기이므로 해당 값의 필드 제거

실제 5개 결과에서 판매자 프로필 ID, 전화번호 형태, 이메일 형태, `$undefined`가 저장되지 않았음을 확인했다.

## 10. 실제 생성 결과

다음 명령으로 샘플 JSON을 생성했다.

```bash
../../.venv/bin/python naver_fleamarket_crawler.py "에어팟 프로3" \
  --sort latest \
  --limit 5 \
  --delay 0.5
```

실행 결과:

- 요청 수: 5개
- 저장 수: 5개
- 상세 조회 실패: 0개
- 정렬: 검색 API `DATE_DESC`, 결과 `createdAt` 내림차순 재확인
- 저장 파일: `output/naver_fleamarket_에어팟_프로3.json`

## 11. 향후 공통 스키마 설계 원칙

1. 각 플랫폼의 원본 필드를 플랫폼 전용 영역에 먼저 보존한다.
2. 이름이 같아도 값의 기준이나 상태 단계가 다르면 공통 필드로 합치지 않는다.
3. 서로 확실히 같은 의미의 필드만 `common`에 추가한다.
4. 제공되지 않은 값을 `0`, `false`, 빈 문자열로 임의 생성하지 않는다.
5. 여러 플랫폼 조사가 끝난 뒤 실제 값과 문서를 비교해 최종 공통 스키마를 설계한다.
