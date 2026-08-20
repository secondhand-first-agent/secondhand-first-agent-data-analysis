"""11번가에서 사용자가 입력한 상품을 검색해 JSON으로 저장한다.

예시:
    python3 elevenst_crawler.py "에어팟 프로3"
    python3 elevenst_crawler.py "아이폰 15 프로" --sort score --limit 20
    python3 elevenst_crawler.py "닌텐도 스위치 OLED" --sort latest --limit 10

주의:
    11번가 검색 화면이 사용하는 공개 JSON 응답과 상품 상세 페이지의
    구조화 데이터를 조회한다. 사이트 변경 시 응답 구조가 달라질 수 있으며
    사용 전에 11번가 이용약관과 수집 권한을 확인하고 낮은 요청 빈도로 실행한다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SEARCH_API_URL = "https://apis.11st.co.kr/search/api/tab"
DETAIL_URL = "https://www.11st.co.kr/products/{product_id}"
# 상품 페이지가 JS로 불러오는 내부 API. 정적 HTML에 없는 값들이 여기 있다.
# 대표 이미지 전체, 도서산간 배송비, 옵션별 가격을 준다.
PDP_DETAIL_URL = (
    "https://www.11st.co.kr/products/v1/pc/products/{product_id}/detail"
)

# 11번가 검색 API의 정렬 코드.
#
# 실측 결과 실제로 동작하는 것은 "N"(최신순) 하나뿐이다. 그 외 값은 인식되지
# 않아 11번가 기본 정렬로 폴백하는데, 그 기본이 곧 랭킹(인기)순이다.
# LP·HP·CP 등 열 가지를 넣어 봤지만 전부 같은 결과가 나왔다.
SORT_VALUES = {
    "popular": "NP",   # 11번가 랭킹순. 미인식 코드가 폴백하는 기본 정렬이다
    "latest": "N",
}

# 새상품은 파는 곳이 한정돼 있어 후보를 많이 볼 필요가 없다. 같은 물건이 여러
# 판매자에게 비슷한 값으로 올라와 있어 상위 몇 건이면 기준가가 잡힌다.
#
# 중고는 매물마다 상태와 가격이 제각각이라 넓게 봐야 하지만 새상품은 반대다.
# 더 모아 봐야 같은 상품이 반복되고, 인기순 아래로 내려갈수록 액세서리가
# 섞일 여지만 는다.
DEFAULT_LIMIT = 4

# 11번가 검색 필터에서 확인한 Apple 브랜드 코드다. 에어팟 검색에서
# 케이스와 호환 액세서리를 제외하고 Apple 본품을 조회하는 데 사용한다.
APPLE_BRAND_CODE = "14635"

HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://search.11st.co.kr",
    "Referer": "https://search.11st.co.kr/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
}

NON_PRODUCT_TERMS = (
    "왼쪽",
    "오른쪽",
    "한쪽",
    "유닛",
    "낱개",
    "단품",
    "본체",
    "케이스",
    "충전기",
    "어댑터",
    "보호필름",
    "스트랩",
    "이어팁",
    "액세서리",
    "악세서리",
    "부품",
    "고장",
    "정크",
    "목업",
    "모형",
    "거치대",
    "키링",
    "파우치",
    "매입",
    "삽니다",
    "구매합니다",
    "구합니다",
    "대여",
)

# 11번가 검색 API는 상품 상태를 주지 않지만 상세 페이지에는 항상 들어 있다.
# "상품상태" 행의 값은 "새상품" 또는 "중고상품"이다.
PRODUCT_STATUS_RE = re.compile(
    r"<th[^>]*>\s*상품상태\s*</th>\s*<td[^>]*>(.*?)</td>", re.S
)
# 중고·렌털 상품은 제목 앞에 뱃지가 붙는다. 일반 새상품에는 없다.
CATEGORY_BADGE_RE = re.compile(r'<em class="category">(.*?)</em>', re.S)
CATEGORY_PATH_RE = re.compile(r'<meta name="keyword" content="(.*?)"')
TAG_RE = re.compile(r"<[^>]+>")

# 렌털은 상품상태가 "새상품"으로 나오지만 소유권을 사는 거래가 아니다.
# 총 지불액 비교에 섞이면 월 구독료가 판매가처럼 읽히므로 따로 걸러낸다.
RENTAL_BADGE = "렌털"
RENTAL_CATEGORY_PREFIX = "렌털/구독"
RENTAL_UNIT_SUFFIX = "/월"


TEXT_ALIASES = (
    (r"airpods", "에어팟"),
    (r"iphone", "아이폰"),
    (r"galaxy", "갤럭시"),
    (r"playstation", "플레이스테이션"),
    (r"\bpro\b", "프로"),
    (r"\bmax\b", "맥스"),
    (r"\bplus\b", "플러스"),
    (r"\bmini\b", "미니"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="11번가에서 입력한 상품의 검색 결과와 상세 정보를 수집합니다."
    )
    parser.add_argument(
        "query",
        help='검색할 상품명. 예: "에어팟 프로3"',
    )
    parser.add_argument(
        "--sort",
        choices=("popular", "latest"),
        default="popular",
        help="popular=인기(랭킹)순, latest=최신순 (기본값: popular)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"수집할 정상 상품 수 (기본값: {DEFAULT_LIMIT}). "
             "새상품은 기준가 확인용이라 중고보다 적게 모은다",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="최대 검색 페이지 수 (기본값: 10)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="요청 사이 대기 시간(초) (기본값: 1.0)",
    )
    parser.add_argument(
        "--include-rental",
        action="store_true",
        help="렌털·구독 상품도 함께 수집한다 (기본값: 제외)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="결과 JSON 경로. 생략하면 검색어를 이용해 자동 생성합니다.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    args.query = args.query.strip()

    if not args.query:
        raise ValueError("검색어를 입력해야 합니다.")
    if args.limit < 1:
        raise ValueError("--limit은 1 이상이어야 합니다.")
    if args.max_pages < 1:
        raise ValueError("--max-pages는 1 이상이어야 합니다.")
    if args.delay < 0:
        raise ValueError("--delay는 0 이상이어야 합니다.")


def default_output_path(query: str) -> Path:
    filename = re.sub(r"[^0-9a-zA-Z가-힣_-]+", "_", query).strip("_")
    filename = filename[:60] or "products"
    return Path("output") / f"elevenst_{filename}.json"


def get_response(
    url: str,
    params: dict[str, Any] | None = None,
    max_retries: int = 3,
    headers: dict[str, str] | None = None,
) -> bytes:
    if params:
        url = f"{url}?{urlencode(params)}"

    for attempt in range(1, max_retries + 1):
        try:
            request = Request(url, headers=headers or HEADERS)
            with urlopen(request, timeout=20) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            print(
                f"[요청 실패] {attempt}/{max_retries}: {error}",
                file=sys.stderr,
            )
            if attempt == max_retries:
                raise
            time.sleep(attempt * 2)

    raise RuntimeError("요청 재시도 처리에 실패했습니다.")


def get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    raw = get_response(url, params)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("11번가 검색 API가 객체가 아닌 응답을 반환했습니다.")
    return data


def get_text(url: str) -> str:
    return get_response(url).decode("utf-8")


def apply_aliases(text: str) -> str:
    normalized = (text or "").lower()
    for pattern, replacement in TEXT_ALIASES:
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def normalize_text(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", apply_aliases(text))


def query_tokens(query: str) -> list[str]:
    return [
        normalize_text(token)
        for token in re.findall(r"[a-z가-힣]+|\d+", apply_aliases(query))
        if normalize_text(token)
    ]


def matches_query(title: str, query: str) -> bool:
    """검색어 구성 요소가 맞고 검색어에 없는 부품 표현이 없는지 확인한다."""

    normalized_title = normalize_text(title)
    normalized_query = normalize_text(query)
    tokens = query_tokens(query)

    if normalized_query not in normalized_title and not all(
        token in normalized_title for token in tokens
    ):
        return False

    for term in NON_PRODUCT_TERMS:
        normalized_term = normalize_text(term)
        if normalized_term in normalized_title and normalized_term not in normalized_query:
            return False

    return True


def search_brand_code(query: str) -> str | None:
    if "에어팟" in normalize_text(query):
        return APPLE_BRAND_CODE
    return None


def extract_search_products(response: dict[str, Any]) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []

    for group in response.get("data") or []:
        if not isinstance(group, dict) or group.get("groupName") != "list":
            continue
        for item in group.get("items") or []:
            if isinstance(item, dict):
                products.append(item)

    return products


def iter_search_products(args: argparse.Namespace) -> Iterator[dict[str, Any]]:
    """검색 결과를 순회한다.

    브랜드 필터를 먼저 걸고, 결과가 모자라면 필터 없이 한 번 더 훑는다.

    필터를 거는 이유는 "에어팟"을 검색했을 때 케이스·호환 액세서리가 아니라
    Apple 본품을 보기 위해서다. 그런데 인기순과 함께 쓰면 11번가가 결과를
    크게 줄인다. 실측하면 에어팟 프로 3 검색에서 브랜드 필터 + 인기순은 3건,
    필터를 빼면 86건이 나온다(최신순은 45건 대 84건).

    그래서 필터를 포기하지 않되, 목표를 못 채우면 필터 없이 보충한다.
    보충분도 matches_query 를 통과해야 하므로 엉뚱한 상품이 섞이지는 않는다.
    """
    seen_product_ids: set[str] = set()
    brand_code = search_brand_code(args.query)

    # 개수 제한은 crawl() 이 판단한다. 여기서 끊으면 상세 조회 단계의
    # 추가 필터링(렌털·제목 불일치) 몫이 사라져 목표를 못 채운다.
    #
    # 제너레이터라 crawl() 이 충분히 모으면 두 번째 순회는 시작되지 않는다.
    if brand_code:
        yield from _search_pages(args, brand_code, seen_product_ids)
        print("[보충 검색] 브랜드 필터 결과를 다 써서 필터 없이 더 찾습니다", flush=True)
    yield from _search_pages(args, None, seen_product_ids)


def _search_pages(
    args: argparse.Namespace,
    brand_code: str | None,
    seen_product_ids: set[str],
) -> Iterator[dict[str, Any]]:
    next_collection_index: int | None = None
    product_more_start_count: int | None = None

    for page in range(1, args.max_pages + 1):
        params: dict[str, Any] = {
            "kwd": args.query,
            "tabId": "TOTAL_SEARCH",
            "sortCd": SORT_VALUES[args.sort],
            "searchMetaYN": "Y",
            "pageNo": page,
        }
        if brand_code:
            params["brandCd"] = brand_code
        if page > 1 and next_collection_index is not None:
            params["nextCollectionIndex"] = next_collection_index
        if page > 1 and product_more_start_count is not None:
            params["prdMoreStartShowCnt"] = product_more_start_count

        response = get_json(SEARCH_API_URL, params)
        if response.get("isBanned"):
            raise RuntimeError("11번가 검색 API가 요청을 차단했습니다.")

        rows = extract_search_products(response)
        print(f"[검색 {page}페이지] {len(rows)}개 결과 확인")

        next_collection_index = response.get("nextCollectionIndex")
        product_more_start_count = response.get("prdMoreStartShowCnt")
        new_product_count = 0

        for row in rows:
            product_id = str(row.get("id") or "")
            title = str(row.get("title") or "")

            if not product_id or product_id in seen_product_ids:
                continue

            seen_product_ids.add(product_id)
            new_product_count += 1

            if row.get("isSoldOut") or row.get("soldOut"):
                continue
            if not matches_query(title, args.query):
                continue

            yield row

        if new_product_count == 0 or not rows:
            break

        total_page = response.get("totalPage")
        if isinstance(total_page, int) and page >= total_page:
            break

        time.sleep(args.delay)


class JsonLdParser(HTMLParser):
    """상품 상세 페이지의 JSON-LD 블록을 읽는다."""

    def __init__(self) -> None:
        super().__init__()
        self.in_json_ld = False
        self.current: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "script":
            return
        attributes = dict(attrs)
        if attributes.get("type") == "application/ld+json":
            self.in_json_ld = True
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.in_json_ld:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_json_ld:
            self.blocks.append("".join(self.current))
            self.in_json_ld = False


def clean_html_text(value: str) -> str:
    return html.unescape(TAG_RE.sub("", value)).strip()


def extract_page_fields(page_html: str) -> dict[str, str]:
    """상세 페이지에서 JSON-LD에 없는 값들을 읽는다.

    찾지 못한 값은 키 자체를 넣지 않는다. 빈 문자열로 채우면
    "수집했는데 값이 없음"과 "수집 못 함"을 구분할 수 없다.
    """
    fields: dict[str, str] = {}

    status = PRODUCT_STATUS_RE.search(page_html)
    if status:
        fields["productStatus"] = clean_html_text(status.group(1))

    badge = CATEGORY_BADGE_RE.search(page_html)
    if badge:
        fields["categoryBadge"] = clean_html_text(badge.group(1))

    path = CATEGORY_PATH_RE.search(page_html)
    if path:
        fields["categoryPath"] = html.unescape(path.group(1)).strip()

    return fields


def is_rental_search_product(search_product: dict[str, Any]) -> bool:
    """검색 결과만으로 렌털을 판별한다.

    렌털은 가격 단위가 "원/월", "원~/월"이다. 상세 조회 전에 걸러
    불필요한 요청을 줄인다.
    """
    unit = search_product.get("unitTxt")
    return isinstance(unit, str) and unit.endswith(RENTAL_UNIT_SUFFIX)


def is_rental_detail(fields: dict[str, str]) -> bool:
    """상세 페이지 값으로 렌털을 판별한다. 검색 단계에서 놓친 것을 잡는다."""
    if fields.get("categoryBadge") == RENTAL_BADGE:
        return True
    return fields.get("categoryPath", "").startswith(RENTAL_CATEGORY_PREFIX)


def pdp_headers(product_id: str) -> dict[str, str]:
    """상세 API는 해당 상품 페이지를 Referer로 요구한다."""
    headers = dict(HEADERS)
    headers["Origin"] = "https://www.11st.co.kr"
    headers["Referer"] = DETAIL_URL.format(product_id=product_id)
    return headers


def get_pdp_json(url: str, product_id: str) -> dict[str, Any]:
    """상세 API를 한 번만 호출한다.

    보조 정보라 실패해도 수집을 멈추지 않는다. 재시도까지 하면
    상품마다 지연이 쌓이므로 max_retries=1로 둔다.
    """
    raw = get_response(url, max_retries=1, headers=pdp_headers(product_id))
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def option_price_range(
    option_api_url: str,
    product_id: str,
) -> dict[str, Any] | None:
    """옵션별 최종 가격의 범위를 구한다.

    검색 결과의 finalPrc는 옵션 중 가장 싼 값이다. 실측 9건 모두
    표시가와 옵션 최저가가 같았고 최고가는 최대 2배까지 벌어졌다.
    품절 옵션은 살 수 없으므로 제외한다.
    """
    data = get_pdp_json(option_api_url, product_id)

    prices = [
        item["finalDiscountPrice"]
        for variation in data.get("variations") or []
        for item in variation.get("items") or []
        if isinstance(item.get("finalDiscountPrice"), int)
        and not item.get("soldOut")
    ]
    if not prices:
        return None

    return {"min": min(prices), "max": max(prices), "count": len(prices)}


def extract_pdp_fields(product_id: str, delay: float) -> dict[str, Any]:
    """상세 API에서 정적 HTML에 없는 값들을 모은다.

    찾지 못한 값은 키를 넣지 않는다. 실패해도 빈 결과를 돌려주고
    나머지 수집은 그대로 진행한다.
    """
    fields: dict[str, Any] = {}

    try:
        data = get_pdp_json(
            PDP_DETAIL_URL.format(product_id=product_id), product_id
        )
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        print(f"[상세 API 실패] {product_id}: {error}", file=sys.stderr)
        return fields

    images = (data.get("headerImage") or {}).get("images") or []
    if images:
        fields["images"] = [str(image) for image in images]

    extra_cost = (
        ((data.get("integDelivery") or {}).get("deliveryInfo") or {})
        .get("extraCostText") or {}
    ).get("pcDlvHtml")
    if extra_cost:
        fields["extraDeliveryCostText"] = clean_html_text(str(extra_cost))

    price_info = data.get("price")
    if isinstance(price_info, dict):
        fields["priceInfo"] = price_info

    option_api_url = (data.get("orderTray") or {}).get("optionApiUrl")
    if option_api_url:
        time.sleep(delay)
        try:
            option_prices = option_price_range(str(option_api_url), product_id)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            print(f"[옵션 조회 실패] {product_id}: {error}", file=sys.stderr)
        else:
            if option_prices:
                fields["optionPrices"] = option_prices

    return fields


def extract_detail(page_html: str) -> dict[str, Any]:
    parser = JsonLdParser()
    parser.feed(page_html)

    for block in parser.blocks:
        try:
            data = json.loads(html.unescape(block))
        except json.JSONDecodeError:
            continue

        nodes = data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "Product":
                return node

    raise ValueError("상세 페이지에서 상품 구조화 데이터를 찾지 못했습니다.")


def get_product_detail(
    search_product: dict[str, Any],
    delay: float = 0.0,
) -> dict[str, Any]:
    product_id = str(search_product["id"])
    url = DETAIL_URL.format(product_id=product_id)
    page_html = get_text(url)
    product = extract_detail(page_html)
    page_fields = extract_page_fields(page_html)
    pdp_fields = extract_pdp_fields(product_id, delay)

    offers = product.get("offers") or {}
    # JSON-LD는 대표 이미지 1장만 준다. 상세 API는 전체를 주므로 그쪽을 쓴다.
    images = pdp_fields.get("images") or product.get("image") or []
    if isinstance(images, str):
        images = [images]

    return {
        "platform": "ELEVENST",
        "platformProductId": product_id,
        "url": url,
        "common": {
            "title": product.get("name") or search_product.get("title"),
            "description": product.get("description"),
            "price": offers.get("price", search_product.get("finalPrc")),
            "currency": offers.get("priceCurrency", "KRW"),
            "images": [str(image) for image in images],
        },
        "elevenst": {
            "search": search_product,
            "detail": {
                "jsonLdProduct": product,
                **page_fields,
                **pdp_fields,
            },
        },
    }


def crawl(args: argparse.Namespace) -> Path:
    validate_args(args)
    output_path = args.output or default_output_path(args.query)

    print(f"[검색 시작] {args.query}")
    print(f"[정렬 기준] {args.sort}")
    print(f"[수집 목표] {args.limit}개")

    products: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    rental_skipped = 0

    for candidate in iter_search_products(args):
        product_id = str(candidate["id"])

        # 1단계 — 검색 결과의 가격 단위로 거른다. 상세 요청을 아낀다.
        if not args.include_rental and is_rental_search_product(candidate):
            rental_skipped += 1
            print(f"[제외] 렌털 상품: {product_id} {candidate.get('title', '')[:40]}")
            continue

        print(f"[{len(products) + 1}/{args.limit}] {product_id} 상세 조회")

        try:
            detail = get_product_detail(candidate, args.delay)
            detail_title = str(detail["common"].get("title") or "")
            if not matches_query(detail_title, args.query):
                print(f"[제외] 검색어와 다른 상품: {detail_title}")
                continue

            # 2단계 — 상세 페이지 뱃지·카테고리로 한 번 더 거른다.
            if not args.include_rental and is_rental_detail(
                detail["elevenst"]["detail"]
            ):
                rental_skipped += 1
                print(f"[제외] 렌털 상품(상세 확인): {detail_title[:40]}")
                continue

            products.append(detail)
        except Exception as error:  # 한 상품 실패로 전체 수집을 중단하지 않는다.
            print(f"[상세 조회 실패] {product_id}: {error}", file=sys.stderr)
            errors.append({
                "productId": product_id,
                "reason": str(error),
            })

        if len(products) >= args.limit:
            break

        time.sleep(args.delay)

    result = {
        "query": args.query,
        "sort": args.sort,
        "requestedCount": args.limit,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(products),
        "failedCount": len(errors),
        "rentalSkippedCount": rental_skipped,
        "products": products,
        "errors": errors,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(f"[완료] {len(products)}개 수집")
    if rental_skipped:
        print(f"[렌털 제외] {rental_skipped}개")
    print(f"[저장 위치] {output_path.resolve()}")

    if len(products) < args.limit:
        print(
            f"[주의] 조건에 맞는 판매 중 상품이 부족해 "
            f"{len(products)}개만 저장했습니다."
        )

    return output_path


def main() -> None:
    try:
        crawl(parse_args())
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        ValueError,
        RuntimeError,
    ) as error:
        print(f"[실행 실패] {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
