"""번개장터에서 사용자가 입력한 상품을 검색해 JSON으로 저장한다.

예시:
    python3 bunjang_crawler.py "에어팟 프로3"
    python3 bunjang_crawler.py "아이폰 15 프로" --sort latest --limit 20
    python3 bunjang_crawler.py "닌텐도 스위치 OLED" --sort score --limit 10

주의:
    번개장터 웹에서 공개적으로 조회되는 내부 데이터 경로를 사용하므로
    사이트 변경 시 응답 구조가 달라질 수 있다. 낮은 요청 빈도로 사용한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE_URL = "https://api.bunjang.co.kr"
WEB_BASE_URL = "https://m.bunjang.co.kr"

SEARCH_URL = f"{API_BASE_URL}/api/search/v8/web/search"
DETAIL_URL = f"{API_BASE_URL}/api/pms/v1/products/{{product_id}}/detail/web"

HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": WEB_BASE_URL,
    "Referer": f"{WEB_BASE_URL}/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
}

# 검색어에 아래 표현이 없는데 결과 제목에만 있으면 부품·구매 글로 판단한다.
# 예: 검색어가 '에어팟 프로3'인데 제목이 '에어팟 프로3 왼쪽 유닛'이면 제외한다.
NON_PRODUCT_TERMS = (
    "왼쪽",
    "오른쪽",
    "한쪽",
    "유닛",
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
    "매입",
    "삽니다",
    "구합니다",
    "구해요",
    "대여",
)

# 같은 제품을 한글·영문으로 다르게 적은 경우를 위한 최소 별칭이다.
# 프로젝트에서 다루는 품목이 늘어나면 이 목록만 확장하면 된다.
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
        description="번개장터에서 입력한 상품의 판매 글과 상세 정보를 수집합니다."
    )
    parser.add_argument(
        "query",
        help='검색할 상품명. 예: "아이폰 15 프로"',
    )
    parser.add_argument(
        "--sort",
        choices=("latest", "score"),
        default="latest",
        help="latest=최신순, score=정확도순 (기본값: latest)",
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
    return Path("output") / f"bunjang_{filename}.json"


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    if params:
        url = f"{url}?{urlencode(params)}"

    for attempt in range(1, max_retries + 1):
        try:
            request = Request(url, headers=HEADERS)
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except (
            HTTPError,
            URLError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            print(
                f"[요청 실패] {attempt}/{max_retries}: {error}",
                file=sys.stderr,
            )
            if attempt == max_retries:
                raise
            time.sleep(attempt * 2)

    raise RuntimeError("요청 재시도 처리에 실패했습니다.")


def normalize_text(text: str) -> str:
    normalized = (text or "").lower()
    for pattern, replacement in TEXT_ALIASES:
        normalized = re.sub(pattern, replacement, normalized)
    return re.sub(r"[^0-9a-z가-힣]", "", normalized)


def query_tokens(query: str) -> list[str]:
    return [
        normalize_text(token)
        for token in re.split(r"\s+", query)
        if normalize_text(token)
    ]


def matches_query(title: str, query: str) -> bool:
    """검색어와 모델명이 맞고, 검색어에 없는 부품 표현이 없는지 확인한다."""

    normalized_title = normalize_text(title)
    normalized_query = normalize_text(query)

    # 공백 차이만 있는 경우를 가장 신뢰한다.
    direct_match = normalized_query in normalized_title

    # 단어 순서가 조금 다른 제목도 허용한다.
    tokens = query_tokens(query)
    token_match = bool(tokens) and all(token in normalized_title for token in tokens)

    if not (direct_match or token_match):
        return False

    for term in NON_PRODUCT_TERMS:
        normalized_term = normalize_text(term)
        if normalized_term in normalized_title and normalized_term not in normalized_query:
            return False

    return True


def mask_personal_info(text: str) -> str:
    text = text or ""
    text = re.sub(
        r"(?<!\d)01[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)",
        "[전화번호 제거]",
        text,
    )
    text = re.sub(
        r"[\w.+-]+@[\w-]+\.[\w.-]+",
        "[이메일 제거]",
        text,
    )
    return text.strip()


def make_image_urls(image_template: str | None, image_count: int) -> list[str]:
    if not image_template:
        return []

    return [
        image_template
        .replace("{cnt}", str(index))
        .replace("{res}", "1200")
        for index in range(1, image_count + 1)
    ]


def get_condition_label(product_specs: list[dict[str, Any]]) -> str | None:
    for spec in product_specs:
        if spec.get("title") == "상품상태":
            return spec.get("content")
    return None


def iter_search_products(args: argparse.Namespace) -> Iterator[dict[str, Any]]:
    cursor: str | None = None
    previous_cursor: str | None = None
    seen_product_ids: set[int] = set()

    for page in range(1, args.max_pages + 1):
        params: dict[str, Any] = {
            "q": args.query,
            "policyKey": "mw.product.keyword",
            "sort": args.sort,
        }
        if cursor:
            params["cursor"] = cursor

        response = get_json(SEARCH_URL, params=params)
        search_response = (
            response["data"]
            ["responses"]
            ["mainGrid"]
            ["searchResponse"]
        )
        rows = search_response.get("data", [])

        print(f"[검색 {page}페이지] {len(rows)}개 결과 확인")

        new_product_count = 0
        for row in rows:
            # 네이버 쇼핑 등 외부 광고를 제외한다.
            if row.get("type") != "PRODUCT":
                continue

            # 번개장터 내부 검색 광고를 제외한다.
            if row.get("ad") is True:
                continue

            product_id = row.get("pid")
            title = str(row.get("name") or "")

            if not product_id or product_id in seen_product_ids:
                continue

            seen_product_ids.add(product_id)
            new_product_count += 1

            if row.get("status") != "SELLING":
                continue
            if not matches_query(title, args.query):
                continue

            yield row

        previous_cursor = cursor
        cursor = search_response.get("nextCursor")

        if new_product_count == 0 or not cursor or cursor == previous_cursor:
            break

        time.sleep(args.delay)


def get_product_detail(product_id: int) -> dict[str, Any]:
    response = get_json(DETAIL_URL.format(product_id=product_id))
    data = response["data"]
    product = data["product"]
    shop = data.get("shop") or {}
    metrics = product.get("metrics") or {}
    trade = product.get("trade") or {}
    brand = product.get("brand") or {}
    category = product.get("category") or {}
    product_specs = data.get("productSpecs") or []

    return {
        "platform": "BUNJANG",
        "platformProductId": str(product["pid"]),
        "url": f"{WEB_BASE_URL}/products/{product['pid']}",
        "title": product.get("name"),
        "description": mask_personal_info(product.get("description") or ""),
        "price": product.get("price"),
        "originalPrice": product.get("originPrice"),
        "currency": "KRW",
        "quantity": product.get("qty"),
        "saleStatus": product.get("saleStatus"),
        "condition": product.get("condition"),
        "conditionLabel": get_condition_label(product_specs),
        "brand": brand.get("name"),
        "category": category.get("name"),
        "categories": [
            item.get("name")
            for item in product.get("categories", [])
            if item.get("name")
        ],
        "location": product.get("geoLabel"),
        "freeShipping": trade.get("freeShipping", False),
        "inPersonTrade": trade.get("inPerson", False),
        "favoriteCount": metrics.get("favoriteCount", 0),
        "viewCount": metrics.get("viewCount", 0),
        "chatCount": metrics.get("buntalkCount", 0),
        "commentCount": metrics.get("commentCount", 0),
        "images": make_image_urls(
            product.get("imageUrl"),
            int(product.get("imageCount") or 0),
        ),
        "seller": {
            "name": shop.get("name"),
            "reviewRating": shop.get("reviewRating"),
            "reviewCount": shop.get("reviewCount"),
            "salesCount": shop.get("salesCount"),
            "isProshop": (shop.get("proshop") or {}).get("isProshop", False),
        },
        "createdAt": product.get("describedAt"),
        "updatedAt": product.get("updatedAt"),
        "isSearchAd": False,
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
        product_id = int(candidate["pid"])
        print(f"[{len(products) + 1}/{args.limit}] {product_id} 상세 조회")

        try:
            detail = get_product_detail(product_id)

            # 검색 결과뿐 아니라 상세 제목도 다시 확인한다.
            if not matches_query(str(detail.get("title") or ""), args.query):
                print(f"[제외] 검색어와 다른 상품: {detail.get('title')}")
                continue
            if detail.get("saleStatus") != "SELLING":
                print(f"[제외] 판매 중 아님: {detail.get('title')}")
                continue

            products.append(detail)
        except Exception as error:  # 한 상품 실패로 전체 수집을 중단하지 않는다.
            print(f"[상세 조회 실패] {product_id}: {error}", file=sys.stderr)
            errors.append({
                "productId": str(product_id),
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
    except (ValueError, KeyError) as error:
        print(f"[실행 실패] {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
