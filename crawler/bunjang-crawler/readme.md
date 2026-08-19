# 번개장터 크롤러 문서

## 1. 개요

`bunjang_crawler.py`는 번개장터에서 사용자가 입력한 검색어로 판매 상품을 조회하고, 검색 결과와 상품 상세 정보를 하나의 JSON 파일로 저장한다.

현재 구현은 다음 원칙을 따른다.

- 검색어, 정렬 방식, 수집 개수를 실행 인자로 받는다.
- 판매 중인 일반 상품만 수집한다.
- 외부 광고, 번개장터 검색 광고, 중복 상품을 제외한다.
- 검색어와 제목이 맞지 않는 상품과 부품·구매·대여 글을 제외한다.
- 상품 설명의 전화번호와 이메일을 마스킹한다.
- 한 상품의 상세 조회가 실패해도 나머지 상품 수집을 계속한다.
- 번개장터 원본 응답을 그대로 저장하지 않고, 다른 중고 플랫폼과 비교하기 쉬운 형태로 필드를 정리해 저장한다.

> 이 크롤러는 번개장터 웹에서 공개적으로 조회되는 내부 데이터 경로를 사용한다. 번개장터의 API 또는 응답 구조가 변경되면 코드 수정이 필요할 수 있으며, 서비스에 부담을 주지 않도록 낮은 요청 빈도로 사용해야 한다.

## 2. 파일 구성

```text
bunjang-crawler/
├── bunjang_crawler.py
├── read.md
└── output/
    └── bunjang_에어팟_프로3.json
```

- `bunjang_crawler.py`: 검색, 필터링, 상세 조회, JSON 저장을 수행하는 실행 파일
- `output/`: 별도의 출력 경로를 지정하지 않았을 때 결과 JSON이 저장되는 폴더
- `read.md`: 크롤러 동작과 출력 스키마를 설명하는 문서

## 3. 실행 방법

Python 3.10 이상이 필요하며 외부 패키지는 사용하지 않는다. 다음 명령은 `bunjang-crawler` 폴더에서 실행하는 것을 기준으로 한다.

```bash
# 에어팟 프로3, 최신순, 기본 20개
python3 bunjang_crawler.py "에어팟 프로3"

# 아이폰 15 프로, 정확도순, 기본 20개
python3 bunjang_crawler.py "아이폰 15 프로" --sort score

# 닌텐도 스위치 OLED, 최신순, 10개
python3 bunjang_crawler.py "닌텐도 스위치 OLED" \
  --sort latest \
  --limit 10
```

### 실행 옵션

| 인자 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `query` | 예 | 없음 | 검색할 상품명 |
| `--sort` | 아니요 | `latest` | `latest`는 최신순, `score`는 정확도순 |
| `--limit` | 아니요 | `20` | 수집할 정상 상품 수. 1 이상이어야 함 |
| `--max-pages` | 아니요 | `10` | 확인할 최대 검색 페이지 수. 1 이상이어야 함 |
| `--delay` | 아니요 | `1.0` | 요청 사이 대기 시간(초). 0 이상이어야 함 |
| `--output` | 아니요 | 자동 생성 | 결과 JSON을 저장할 경로 |

`--output`을 생략하면 검색어의 공백과 특수문자를 `_`로 바꾸어 아래 형식으로 저장한다.

```text
output/bunjang_{검색어}.json
```

예를 들어 `에어팟 프로3`의 기본 출력 경로는 `output/bunjang_에어팟_프로3.json`이다. 출력 경로는 명령을 실행한 현재 작업 디렉터리를 기준으로 계산된다.

## 4. 수집 과정

1. 검색 API를 최신순 또는 정확도순으로 호출한다.
2. 커서를 이용해 다음 검색 페이지를 조회한다.
3. 검색 결과에서 광고, 중복, 판매 완료 상품을 제외한다.
4. 제목을 정규화해 검색어와 일치하는지 검사한다.
5. 검색어에는 없지만 제목에 부품·구매·대여 관련 표현이 있으면 제외한다.
6. 통과한 상품의 상세 API를 호출한다.
7. 상세 제목과 판매 상태를 다시 검사한다.
8. 필요한 필드를 공통 출력 형태로 변환해 저장한다.
9. 정상 상품이 `--limit` 개수에 도달하면 종료한다.

조건에 맞는 상품이 부족하거나 최대 검색 페이지에 도달하면 요청 개수보다 적게 저장될 수 있다. 실제 저장 개수는 최상위 `count` 필드에서 확인한다.

### 사용하는 번개장터 데이터 경로

| 용도 | 경로 | 주요 사용 데이터 |
| --- | --- | --- |
| 상품 검색 | `/api/search/v8/web/search` | 상품 ID, 제목, 상품 유형, 광고 여부, 판매 상태, 다음 페이지 커서 |
| 상품 상세 | `/api/pms/v1/products/{product_id}/detail/web` | 가격, 상태, 설명, 카테고리, 거래 방식, 통계, 이미지, 판매자 정보 |

검색 요청에는 `q`, `policyKey`, `sort`, 필요 시 `cursor`가 전달된다. 이 경로와 원본 응답 구조는 번개장터 내부 변경에 따라 달라질 수 있다.

## 5. 필터링 및 데이터 처리

### 검색어 일치 처리

- 영문은 소문자로 바꾸고 공백과 특수문자를 제거한다.
- `AirPods → 에어팟`, `iPhone → 아이폰`, `Pro → 프로` 등 일부 한글·영문 표기를 통일한다.
- 정규화된 전체 검색어가 제목에 포함되거나, 검색어의 모든 단어가 제목에 포함되면 일치로 판단한다.

### 제외 대상

- `type`이 `PRODUCT`가 아닌 외부 광고
- `ad`가 `true`인 번개장터 검색 광고
- 이미 확인한 상품 ID
- 판매 상태가 `SELLING`이 아닌 상품
- 검색어와 제목이 맞지 않는 상품
- 검색어에는 없지만 제목에 `유닛`, `케이스`, `부품`, `고장`, `매입`, `삽니다`, `대여` 등의 표현이 들어간 글

### 개인정보 및 위치 처리

- 설명의 휴대전화 번호는 `[전화번호 제거]`로 변경한다.
- 설명의 이메일은 `[이메일 제거]`로 변경한다.
- 판매자 고유 ID와 위도·경도는 저장하지 않는다.
- 번개장터가 제공하는 지역명 `geoLabel`만 `location`에 저장한다.

## 6. 저장되는 JSON 구조

출력 JSON은 실행 정보, 상품 배열, 오류 배열로 구성된다.

```json
{
  "query": "에어팟 프로3",
  "sort": "latest",
  "requestedCount": 5,
  "collectedAt": "2026-08-19T06:43:20.214510+00:00",
  "count": 5,
  "failedCount": 0,
  "products": [],
  "errors": []
}
```

### 최상위 필드

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `query` | string | 실행 시 입력한 검색어 |
| `sort` | string | 적용한 정렬 방식: `latest` 또는 `score` |
| `requestedCount` | number | `--limit`으로 요청한 정상 상품 수 |
| `collectedAt` | string | 수집 완료 시각. UTC 기준 ISO 8601 형식 |
| `count` | number | 실제로 저장된 정상 상품 수 |
| `failedCount` | number | 상세 조회 중 오류가 발생한 상품 수 |
| `products` | array | 정규화된 상품 객체 배열 |
| `errors` | array | 상세 조회 오류 객체 배열 |

### 상품 필드

타입에 `null`이 포함된 필드는 번개장터 응답에 값이 없을 수 있다.

| 필드 | 타입 | 번개장터 원본 위치 | 설명 |
| --- | --- | --- | --- |
| `platform` | string | 코드에서 지정 | 플랫폼 식별자. 항상 `BUNJANG` |
| `platformProductId` | string | `data.product.pid` | 번개장터 상품 ID를 문자열로 변환한 값 |
| `url` | string | 상품 ID로 생성 | 번개장터 모바일 상품 페이지 URL |
| `title` | string \| null | `data.product.name` | 상품 제목 |
| `description` | string | `data.product.description` | 개인정보를 마스킹한 상품 설명 |
| `price` | number \| null | `data.product.price` | 현재 판매 가격 |
| `originalPrice` | number \| null | `data.product.originPrice` | 번개장터가 제공하는 원래 가격 |
| `currency` | string | 코드에서 지정 | 통화. 항상 `KRW` |
| `quantity` | number \| null | `data.product.qty` | 판매 수량 |
| `saleStatus` | string \| null | `data.product.saleStatus` | 상세 상품 판매 상태. 수집 결과는 `SELLING`만 포함 |
| `condition` | string \| null | `data.product.condition` | 상품 상태 코드 |
| `conditionLabel` | string \| null | `data.productSpecs` | `상품상태` 항목의 한글 표시값 |
| `brand` | string \| null | `data.product.brand.name` | 브랜드명 |
| `category` | string \| null | `data.product.category.name` | 대표 카테고리명 |
| `categories` | array[string] | `data.product.categories` | 상위부터 하위까지의 카테고리명 목록 |
| `location` | string \| null | `data.product.geoLabel` | 공개된 거래 지역명. 좌표는 저장하지 않음 |
| `freeShipping` | boolean | `data.product.trade.freeShipping` | 무료 배송 여부 |
| `inPersonTrade` | boolean | `data.product.trade.inPerson` | 직거래 가능 여부 |
| `favoriteCount` | number | `data.product.metrics.favoriteCount` | 관심 수 |
| `viewCount` | number | `data.product.metrics.viewCount` | 조회 수 |
| `chatCount` | number | `data.product.metrics.buntalkCount` | 번개톡 수 |
| `commentCount` | number | `data.product.metrics.commentCount` | 댓글 수 |
| `images` | array[string] | `imageUrl`, `imageCount`로 생성 | 해상도 `1200`으로 변환한 상품 이미지 URL 목록 |
| `seller` | object | `data.shop` | 필요한 정보만 정리한 판매자 객체 |
| `createdAt` | string \| null | `data.product.describedAt` | 상품 등록 시각 |
| `updatedAt` | string \| null | `data.product.updatedAt` | 상품 수정 시각 |
| `isSearchAd` | boolean | 검색 필터 결과 | 광고를 제외한 뒤 저장하므로 항상 `false` |

원본 숫자나 불리언 값이 누락된 경우 거래 여부와 통계 수치는 각각 `false`, `0`을 기본값으로 사용한다. 이미지 원본 템플릿이 없으면 `images`는 빈 배열이 된다.

### 판매자 필드

| 필드 | 타입 | 번개장터 원본 위치 | 설명 |
| --- | --- | --- | --- |
| `name` | string \| null | `data.shop.name` | 상점 이름 |
| `reviewRating` | number \| null | `data.shop.reviewRating` | 리뷰 평점 |
| `reviewCount` | number \| null | `data.shop.reviewCount` | 리뷰 수 |
| `salesCount` | number \| null | `data.shop.salesCount` | 판매 수 |
| `isProshop` | boolean | `data.shop.proshop.isProshop` | 프로상점 여부 |

판매자 UID와 그 밖의 개인 식별 정보는 저장하지 않는다.

### 오류 필드

상품 상세 조회에 실패하면 `errors`에 아래 형식으로 기록한다.

```json
{
  "productId": "상품 ID",
  "reason": "오류 내용"
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `productId` | string | 상세 조회에 실패한 번개장터 상품 ID |
| `reason` | string | 실행 중 발생한 오류 메시지 |

## 7. 요청 실패 처리

- 검색 및 상세 요청의 타임아웃은 20초다.
- HTTP, 네트워크, 타임아웃, 디코딩, JSON 파싱 오류는 최대 3회 재시도한다.
- 재시도 전에는 시도 횟수에 따라 2초, 4초씩 대기한다.
- 개별 상품 상세 조회가 최종 실패하면 `errors`에 기록하고 다음 상품으로 진행한다.
- 검색 응답에서 필수 구조가 사라진 경우 실행을 실패 처리한다.

## 8. 다른 중고 플랫폼 크롤러 추가 시 기준

플랫폼별 원본 응답은 달라도 결과 JSON은 가능한 한 이 문서의 공통 필드명을 유지한다.

- `platform`과 `platformProductId`로 출처와 플랫폼 내부 ID를 구분한다.
- 실행 정보는 `query`, `sort`, `requestedCount`, `collectedAt`, `count`, `failedCount`를 사용한다.
- 상품 정보는 `products`, 개별 조회 실패는 `errors`에 저장한다.
- 가격에는 `currency`를 함께 기록한다.
- 원본 값이 없는 필드는 의미에 따라 `null`, `false`, `0`, 빈 배열 중 하나를 일관되게 사용한다.
- 플랫폼 전용 필드가 필요하면 공통 필드를 바꾸기보다 별도 필드를 추가하고 해당 플랫폼 문서에 원본 위치와 의미를 기록한다.
- 전화번호, 이메일, 사용자 고유 ID, 정확한 좌표 등 분석에 불필요한 개인정보는 저장하지 않는다.

새 플랫폼 폴더에도 실행 파일, `output/`, 필드 문서를 같은 형태로 두면 플랫폼별 JSON 구조를 비교하고 이후 통합 스키마를 설계하기 쉽다.
