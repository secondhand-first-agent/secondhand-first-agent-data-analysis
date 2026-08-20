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

SORT_VALUES = {
    "latest": "N",
    "score": "NP",
}

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
        choices=("latest", "score"),
        default="latest",
        help="latest=최신순, score=11번가 랭킹순 (기본값: latest)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="수집할 정상 상품 수 (기본값: 20)",
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
) -> bytes:
    if params:
        url = f"{url}?{urlencode(params)}"

    for attempt in range(1, max_retries + 1):
        try:
            request = Request(url, headers=HEADERS)
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
    seen_product_ids: set[str] = set()
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
        brand_code = search_brand_code(args.query)
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


def get_product_detail(search_product: dict[str, Any]) -> dict[str, Any]:
    product_id = str(search_product["id"])
    url = DETAIL_URL.format(product_id=product_id)
    product = extract_detail(get_text(url))

    offers = product.get("offers") or {}
    images = product.get("image") or []
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

    for candidate in iter_search_products(args):
        product_id = str(candidate["id"])
        print(f"[{len(products) + 1}/{args.limit}] {product_id} 상세 조회")

        try:
            detail = get_product_detail(candidate)
            detail_title = str(detail["common"].get("title") or "")
            if not matches_query(detail_title, args.query):
                print(f"[제외] 검색어와 다른 상품: {detail_title}")
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
        "products": products,
        "errors": errors,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(f"[완료] {len(products)}개 수집")
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
