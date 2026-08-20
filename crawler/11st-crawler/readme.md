# 11번가 크롤러 문서

## 1. 개요

`elevenst_crawler.py`는 11번가에서 사용자가 입력한 상품을 검색하고, 검색 API와 상세 페이지에 공개된 데이터를 JSON으로 저장한다.

실행 방식과 최상위 출력 구조는 번개장터·중고나라·N플리마켓 크롤러와 동일하지만 데이터 구조는 11번가 원본 의미를 우선한다.

- 검색어, 정렬 방식, 수집 개수, 최대 페이지, 요청 간격, 출력 경로를 실행 인자로 받는다.
- Playwright를 사용하지 않고 11번가 검색 화면이 사용하는 JSON API를 요청한다.
- 광고·추천 영역이 아닌 `groupName=list`의 일반 상품만 수집한다.
- 품절, 중복, 부품, 액세서리 상품을 제외한다.
- 에어팟 검색에는 11번가의 Apple 브랜드 필터를 적용해 본품을 우선한다.
- 검색 API 원본과 상세 페이지의 JSON-LD를 분리해 보존한다.
- 상세 페이지의 `상품상태` 행을 읽어 새상품과 중고상품을 구분한다.
- 렌털·구독 상품을 두 단계로 걸러낸다.
- 상품 페이지가 쓰는 내부 상세 API에서 대표 이미지 전체, 도서산간 배송비, 옵션별 가격을 가져온다.
- 플랫폼 간 의미가 확실히 같은 최소 데이터만 `common`에 저장한다.
- 11번가 전용 필드는 이름이나 의미를 바꾸지 않고 `elevenst` 아래에 저장한다.

> 이 크롤러는 11번가 웹 검색 화면이 사용하는 내부 JSON API와 공개 상품 상세 페이지를 사용한다. 공식 개발자용 API가 아니므로 URL과 응답 구조가 예고 없이 변경될 수 있다. 사용 전에 11번가 이용약관과 수집 권한을 확인하고 서비스에 부담을 주지 않도록 낮은 요청 빈도로 실행해야 한다.

## 2. 파일 구성

```text
11st-crawler/
├── elevenst_crawler.py
├── readme.md
└── output/
    └── elevenst_에어팟_프로3.json
```

저장소 루트의 `.venv`를 공용 가상환경으로 사용할 수 있으며 가상환경 자체는 Git에 저장하지 않는다. 크롤러는 Python 3.10 이상에서 외부 패키지 없이 실행된다.

## 3. 실행 방법

다음 명령은 `crawler/11st-crawler` 폴더에서 실행하는 것을 기준으로 한다.

```bash
# 에어팟 프로3, 최신순, 기본 20개
python3 elevenst_crawler.py "에어팟 프로3"

# 아이폰 15 프로, 11번가 랭킹순, 기본 20개
python3 elevenst_crawler.py "아이폰 15 프로" --sort score

# 닌텐도 스위치 OLED, 최신순, 10개
python3 elevenst_crawler.py "닌텐도 스위치 OLED" \
  --sort latest \
  --limit 10

# 루트 공용 가상환경으로 에어팟 프로3 5개 수집
../../.venv/bin/python elevenst_crawler.py "에어팟 프로3" \
  --sort latest \
  --limit 5
```

### 실행 옵션

| 인자 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `query` | 예 | 없음 | 검색할 상품명 |
| `--sort` | 아니요 | `latest` | `latest`는 최신순, `score`는 11번가 랭킹순 |
| `--limit` | 아니요 | `20` | 수집할 정상 상품 수. 1 이상이어야 함 |
| `--max-pages` | 아니요 | `10` | 확인할 최대 검색 페이지 수. 1 이상이어야 함 |
| `--delay` | 아니요 | `1.0` | 요청 사이 대기 시간(초). 0 이상이어야 함 |
| `--include-rental` | 아니요 | 끄기 | 렌털·구독 상품도 함께 수집한다 |
| `--output` | 아니요 | 자동 생성 | 결과 JSON을 저장할 경로 |

정렬값은 11번가 검색 화면의 값으로 변환한다.

| CLI 값 | 11번가 `sortCd` | 의미 |
| --- | --- | --- |
| `latest` | `N` | 최신순 |
| `score` | `NP` | 11번가 랭킹순 |

`--output`을 생략하면 현재 작업 디렉터리를 기준으로 `output/elevenst_{검색어}.json`에 저장한다.

## 4. API 및 수집 과정

검색 API는 다음 주소를 사용한다.

```text
https://apis.11st.co.kr/search/api/tab
```

기본 요청 파라미터는 다음과 같다.

| 파라미터 | 설명 |
| --- | --- |
| `kwd` | 검색어 |
| `tabId=TOTAL_SEARCH` | 통합검색 탭 |
| `sortCd` | 11번가 정렬 코드 |
| `searchMetaYN=Y` | 검색 메타데이터 포함 요청 |
| `pageNo` | 검색 페이지 번호 |

수집 순서는 다음과 같다.

1. 검색어와 정렬값을 포함해 검색 JSON API를 요청한다.
2. 에어팟 검색이면 Apple 브랜드 코드 `14635`를 `brandCd`에 추가한다.
3. 응답의 `isBanned`를 확인하고 차단 응답이면 실행을 중단한다.
4. `data`에서 `groupName=list`인 일반 검색 영역만 합친다.
5. 상품 `id`를 기준으로 중복을 제거한다.
6. `isSoldOut` 또는 `soldOut`인 상품을 제외한다.
7. 제목을 정규화해 검색어 일치 여부를 검사한다.
8. 검색어에는 없지만 제목에 케이스·유닛·부품·액세서리·매입·대여 표현이 있으면 제외한다.
9. `/products/{product_id}`의 JSON-LD에서 `Product` 객체를 추출한다.
10. 상세 제목을 다시 검사하고 정상 상품이 `--limit`에 도달하면 종료한다.

2페이지부터는 직전 응답의 `nextCollectionIndex`와 `prdMoreStartShowCnt`를 다음 요청에 전달한다. 영문과 한글 상품명 비교를 위해 `AirPods → 에어팟`, `iPhone → 아이폰`, `Pro → 프로` 등 최소 별칭만 필터링에 사용하며 저장되는 원본 제목은 바꾸지 않는다.

## 5. 데이터 구조 설계 원칙

상품 하나는 세 영역으로 나뉜다.

```json
{
  "platform": "ELEVENST",
  "platformProductId": "9490419884",
  "url": "https://www.11st.co.kr/products/9490419884",
  "common": {
    "title": "에어팟 프로 3세대 (USB-C) MFHP4KH/A 화이트 GD",
    "description": null,
    "price": 399900,
    "currency": "KRW",
    "images": [
      "https://cdn.011st.com/11dims/resize/792x792/quality/75/11src/product/9490419884/B.webp"
    ]
  },
  "elevenst": {
    "search": {},
    "detail": {
      "jsonLdProduct": {}
    }
  }
}
```

### 공통 식별 영역

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `platform` | string | 플랫폼 식별자. 항상 `ELEVENST` |
| `platformProductId` | string | 11번가 검색 상품 `id`를 문자열로 표현한 값 |
| `url` | string | 상품 ID로 구성한 11번가 상세 페이지 URL |

### `common` 영역

| 필드 | 타입 | 출처 | 설명 |
| --- | --- | --- | --- |
| `title` | string | JSON-LD `Product.name`, 없으면 검색 `title` | 상품명 |
| `description` | string \| null | JSON-LD `Product.description` | 상세 설명. 미제공 시 `null` |
| `price` | number \| null | JSON-LD `offers.price`, 없으면 검색 `finalPrc` | 상세 페이지 표시 가격 |
| `currency` | string | JSON-LD `offers.priceCurrency`, 없으면 `KRW` | 가격 통화 |
| `images` | array[string] | JSON-LD `Product.image` | 상품 이미지 URL 목록 |

검색 시점의 가격, 배송, 판매자, 할인, 평점 등 11번가 고유 데이터는 `common`에 의미를 바꿔 넣지 않고 `elevenst.search`에 원본 그대로 저장한다.

### `elevenst` 영역

- `elevenst.search`: 검색 API가 반환한 11번가 상품 객체
- `elevenst.detail.jsonLdProduct`: 상세 페이지의 schema.org `Product` 객체

검색 가격 `finalPrc`와 상세 JSON-LD의 `offers.price`는 할인 적용 시점이나 상세 페이지 정책에 따라 다를 수 있으므로 둘 다 원본 위치에 보존한다.

`elevenst.detail`에는 JSON-LD 외에 아래 값이 함께 들어간다.
**찾지 못한 값은 키 자체를 넣지 않는다.** 빈 문자열로 채우면 "수집했는데 값이 없음"과
"수집하지 못함"을 구분할 수 없다.

| 키 | 출처 | 예시 |
| --- | --- | --- |
| `productStatus` | 상세 페이지 `상품상태` 행 | `새상품` · `중고상품` |
| `categoryBadge` | 제목 앞 뱃지 | `중고` · `렌털` · `해외` |
| `categoryPath` | `<meta name="keyword">` | `모니터>일반 모니터>…` |
| `images` | 상세 API `headerImage.images[]` | 대표 이미지 전체 |
| `extraDeliveryCostText` | 상세 API `integDelivery` | `제주지역 3,500원, 도서산간지역 6,500원` |
| `priceInfo` | 상세 API `price` | `sellPrice` · `finalDscPrice` 등 |
| `optionPrices` | 옵션 API | `{"min": 26420, "max": 30950, "count": 4}` |

## 5-1. 상품상태를 상세 페이지에서 읽는 이유

**검색 API에는 상태 필드가 없다.** `itemCondition`은 표본 50건 전부 `null`이었다.

새상품 마켓이니 항상 `새상품`으로 두는 방안을 검토했으나 실제로 중고가 섞여 있어 폐기했다.
`중고 아이폰`을 검색하면 `A등급 아이폰 12 프로 맥스 중고폰 공기계`가 나온다.

상태는 상세 페이지의 `상품상태` 행에 있다. 표본 35건 전부 이 행이 있었다.

```html
<th scope='row'>상품상태</th><td>중고상품</td>
```

| 값 | 건수 |
| --- | ---: |
| `새상품` | 31 |
| `중고상품` | 4 |

> 리퍼브는 별도 값이 아니다. `리퍼 노트북`·`리퍼브 냉장고` 검색 결과도 `새상품`으로 나온다.

## 5-2. 렌털을 제외하는 방법

렌털·구독 상품은 **`상품상태`가 `새상품`으로 나온다.** 물건은 새것이지만 소유권을 사는
거래가 아니다. 월 구독료가 판매가로 읽히면 가격 비교가 무너지므로 기본적으로 제외한다.

| 단계 | 근거 | 렌털 판정 |
| --- | --- | --- |
| 1. 검색 결과 | `unitTxt` | `원/월` · `원~/월` |
| 2. 상세 페이지 | `categoryBadge` · `categoryPath` | `렌털` · `렌털/구독 서비스…` |

1단계에서 걸러 상세 요청을 아끼고, 놓친 것을 2단계에서 잡는다.
**교차검증 49건에서 오탐·누락이 0건이었다.**

```text
[제외] 렌털 상품: 9561407554 [구독/렌탈] (72개월약정) LG 베스트 정수기 가전구독…
[완료] 3개 수집
[렌털 제외] 1개
```

제목의 "렌탈" 문자열로 거르면 안 된다. `정수기렌탈가격비교` 같은 검색어 낚시 제목을 단
일반 침대 상품이 대량으로 걸린다. `unitTxt`는 이것을 정확히 구분한다.

`--include-rental`을 주면 렌털도 수집한다.

## 5-3. 상세 API에서 더 가져오는 값

```text
https://www.11st.co.kr/products/v1/pc/products/{상품번호}/detail
```

상품 페이지가 JS로 부르는 내부 API다. 정적 HTML과 JSON-LD에 없는 값이 여기 있다.
**보조 정보라 실패해도 수집을 멈추지 않고 재시도도 하지 않는다.** 재시도까지 하면
상품마다 지연이 쌓인다.

| 값 | 실측 20건 |
| --- | --- |
| 대표 이미지 전체 | 평균 1.45장 (JSON-LD는 항상 1장) |
| 도서산간 배송비 | 6건 |
| 옵션별 가격 | 3건 |

**옵션 가격이 중요하다.** 검색 결과의 `finalPrc`는 **옵션 중 가장 싼 값**이다.
`maxDiscountInfo.hasOptionPrice`가 `true`인 상품 9건을 측정한 결과
**9건 모두 표시가와 옵션 최저가가 일치**했고 최고가는 최대 107,300원(2배)까지 벌어졌다.

품절 옵션은 살 수 없으므로 범위에서 제외한다.

> `optPrcText`(`"~"`)는 화면 표시용 문자열이다. 판별에는 구조화된
> `maxDiscountInfo.hasOptionPrice`를 쓴다. 표본 504건에서 두 값은 예외 없이 일치했다.

## 5-4. `description`이 비어 있는 이유

11번가 상품 설명은 **판매자가 올린 이미지**다. JSON-LD에 `description` 자체가 없고
정적 HTML에는 상품고시 테이블만 있다. 설명 이미지는 JS가 나중에 불러오므로
우리가 받는 HTML에 들어 있지 않다.

이 때문에 통합 스키마에서 11번가의 `description`은 `null`이다.
**설명 길이나 이미지 개수를 스코어링에 쓰면 11번가가 부당하게 불리해진다.**

## 6. 최상위 결과 구조

```json
{
  "query": "에어팟 프로3",
  "sort": "latest",
  "requestedCount": 5,
  "collectedAt": "2026-08-20T00:28:12.418956+00:00",
  "count": 5,
  "failedCount": 0,
  "rentalSkippedCount": 1,
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
| `rentalSkippedCount` | number | 렌털로 판정해 제외한 수 |
| `products` | array | 상품 객체 배열 |
| `errors` | array | 상세 조회 오류 배열 |

## 7. `elevenst.search` 주요 원본 필드

아래 필드는 실제 수집 결과에서 확인된 검색 API 상품 필드다. 상품에 따라 일부 필드는 없을 수 있으며 값은 별도 의미 변환 없이 저장한다.

| 필드 | 확인된 타입 | 설명 |
| --- | --- | --- |
| `id` | string | 11번가 상품 번호 |
| `title` | string | 검색 결과 상품명 |
| `linkUrl` | string | 검색 결과의 상세 페이지 URL |
| `imageUrl` | string | 검색 결과 이미지 URL |
| `finalPrc` | number | 검색 결과의 최종 표시 가격 |
| `selPrc` | string | 11번가 검색 원본 판매 가격 문자열 |
| `discountPrice` | number | 할인 금액 원본값 |
| `discountRate` | number | 할인율 원본값 |
| `deliveryDescription` | string | 배송비 또는 배송 설명 |
| `sellerNickName` | string | 공개 판매자 이름 |
| `sellerUrl` | string | 판매자 스토어 URL |
| `brandEngNm` | string | 브랜드 영문명 |
| `satisfactionScore` | string | 판매자 또는 상품 만족도 원본값 |
| `reviewCountText` | string | 리뷰 수 표시 문자열 |
| `isSoldOut`, `soldOut` | boolean | 품절 여부 원본값 |
| `isOfficial` | boolean | 공식 판매 표시 원본값 |
| `is11stLowPrcPrd` | boolean | 11번가 최저가 표시 원본값 |
| `is30DayLowPrcPrd` | boolean | 30일 최저가 표시 원본값 |
| `benefitText` | array | 적립 등 혜택 표시 원본값 |
| `logData` | object | 검색 영역과 노출 순서를 포함한 11번가 로그 원본값 |
| `maxDiscountInfo` | object | 상품·판매자·가격 관련 할인 계산 원본값 |

필드 이름만으로 의미를 확정하기 어려운 값은 추론하지 않고 원본값으로 기록한다.

## 8. `elevenst.detail.jsonLdProduct` 원본 필드

상세 페이지의 schema.org `Product` 객체를 구조 그대로 저장한다.

| 필드 | 확인된 타입 | 설명 |
| --- | --- | --- |
| `@context` | string | schema.org 문맥 |
| `@type` | string | JSON-LD 유형. `Product` |
| `name` | string | 상세 상품명 |
| `image` | string | 상세 대표 이미지 URL |
| `brand` | object | 브랜드 이름과 JSON-LD 유형 |
| `productID` | string | 11번가 상품 번호 |
| `category` | string | 상세 페이지 카테고리 경로 |
| `offers` | object | 가격, 통화, 재고, 상세 URL |
| `aggregateRating` | object | 평점과 리뷰 수. 제공되는 상품에만 존재 |

`offers`에는 `price`, `priceCurrency`, `availability`, `url`, `priceSpecification` 등이 포함될 수 있다.

## 9. 저장하거나 만들지 않는 데이터

- 로그인 사용자 정보, 쿠키, 장바구니 정보는 요청하거나 저장하지 않는다.
- 검색 API에 없는 등록 시각은 상품 번호나 응답 순서로 추정해 만들지 않는다.
- `latest`는 11번가 서버의 `sortCd=N` 응답 순서를 그대로 사용한다.
- 배송비 문자열을 임의의 `freeShipping` 불리언으로 바꾸지 않는다.
- 평점이나 리뷰가 없는 경우 임의의 `0`을 만들지 않는다.
- 검색 가격과 상세 가격이 다를 때 한쪽 값으로 덮어쓰지 않는다.
- 광고 영역인 `recommendAdPrd`, `topAdArea` 등은 수집 대상에서 제외한다.

## 10. 실제 수집 결과

2026-08-20에 다음 명령으로 API 기반 수집을 검증했다.

```bash
../../.venv/bin/python elevenst_crawler.py "에어팟 프로3" \
  --sort latest \
  --limit 5
```

| 항목 | 결과 |
| --- | --- |
| 요청 상품 수 | 5개 |
| 저장 상품 수 | 5개 |
| 상세 조회 실패 | 0개 |
| 검색 1페이지에서 확인한 Apple 상품 | 45개 |
| 상세 JSON-LD 가격 범위 | 368,080원~677,400원 |
| Playwright 사용 | 사용하지 않음 |

저장된 상품 번호는 최신순 API 응답 순서대로 다음과 같다.

1. `9490419884`
2. `9480391899`
3. `9473781625`
4. `9471430820`
5. `9429773147`

판매 상품, 가격, 순서는 실행 시점에 따라 달라진다.

## 11. 오류 처리

검색 API와 상세 페이지 요청의 타임아웃은 20초이며 네트워크, HTTP, 타임아웃 오류는 최대 3회 재시도한다. 검색 응답의 `isBanned`가 참이면 차단 상태로 판단해 실행을 중단한다.

개별 상세 조회가 최종 실패하면 전체 수집을 중단하지 않고 다음 형식으로 `errors`에 기록한다.

```json
{
  "productId": "상품 ID",
  "reason": "오류 내용"
}
```

## 12. 유지보수 기준

11번가 검색 API는 공식 개발자용 API가 아니므로 다음 항목을 실행 시 확인해야 한다.

1. 응답이 JSON 객체인지 확인한다.
2. `isBanned`가 참인지 확인한다.
3. `data[].groupName=list`와 `items`가 유지되는지 확인한다.
4. `id`, `title`, `finalPrc`, `linkUrl` 등 필수 검색 필드 변화를 확인한다.
5. 상세 페이지에 `application/ld+json`의 `Product`가 유지되는지 확인한다.
6. 요청 간격을 낮게 유지하고 불필요한 상세 요청을 만들지 않는다.
