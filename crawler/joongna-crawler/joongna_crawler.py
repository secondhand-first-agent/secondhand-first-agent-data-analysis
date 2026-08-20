"""중고나라에서 사용자가 입력한 상품을 검색해 JSON으로 저장한다.

예시:
    python3 joongna_crawler.py "에어팟 프로3"
    python3 joongna_crawler.py "아이폰 15 프로" --sort score --limit 20
    python3 joongna_crawler.py "닌텐도 스위치 OLED" --sort latest --limit 10

주의:
    중고나라 웹의 공개 검색 페이지와 구조화 데이터를 사용하므로
    사이트 변경 시 응답 구조가 달라질 수 있다. 낮은 요청 빈도로 사용한다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


WEB_BASE_URL = "https://web.joongna.com"
SEARCH_URL = f"{WEB_BASE_URL}/search/{{query}}"
DETAIL_URL = f"{WEB_BASE_URL}/product/{{product_id}}"

SORT_VALUES = {
    "latest": "RECENT_SORT",
    "score": "RECOMMEND_SORT",
}

HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": f"{WEB_BASE_URL}/",
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
    "매입",
    "삽니다",
    "구매합니다",
    "구합니다",
    "구해요",
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
        description="중고나라에서 입력한 상품의 판매 글과 상세 정보를 수집합니다."
    )
    parser.add_argument(
        "query",
        help='검색할 상품명. 예: "아이폰 15 프로"',
    )
    parser.add_argument(
        "--sort",
        choices=("latest", "score"),
        default="latest",
        help="latest=최신순, score=추천순 (기본값: latest)",
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
    return Path("output") / f"joongna_{filename}.json"


def get_text(
    url: str,
    params: dict[str, Any] | None = None,
    max_retries: int = 3,
) -> str:
    if params:
        url = f"{url}?{urlencode(params)}"

    for attempt in range(1, max_retries + 1):
        try:
            request = Request(url, headers=HEADERS)
            with urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8")
        except (
            HTTPError,
            URLError,
            TimeoutError,
            UnicodeDecodeError,
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
    direct_match = normalized_query in normalized_title
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


def decode_search_product(raw_product: str) -> dict[str, Any]:
    """Next.js 스트림 안에서 이중 이스케이프된 상품 JSON을 복원한다."""

    decoded_text = json.loads(f'"{raw_product}"')
    return json.loads(decoded_text)


def extract_search_products(page_html: str) -> list[dict[str, Any]]:
    """검색 페이지의 Next.js 데이터에서 공개 상품 목록을 추출한다."""

    pattern = re.compile(
        r'\{\\"seq\\":\d+,'
        r'\\"productPositionNo\\":.*?'
        r'\\"objectType\\":\\"product\\",'
        r'\\"wishYn\\":\d+\}',
        re.DOTALL,
    )
    products: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for match in pattern.finditer(page_html):
        try:
            product = decode_search_product(match.group(0))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        product_id = product.get("seq")
        if not product_id or product_id in seen_ids:
            continue

        seen_ids.add(product_id)
        products.append(product)

    return products


def parse_sort_date(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone(timedelta(hours=9))
        )
    except ValueError:
        return None


def iter_search_products(args: argparse.Namespace) -> Iterator[dict[str, Any]]:
    search_url = SEARCH_URL.format(query=quote(args.query, safe=""))
    seen_product_ids: set[int] = set()

    for page in range(1, args.max_pages + 1):
        page_html = get_text(
            search_url,
            params={
                "sort": SORT_VALUES[args.sort],
                "page": page,
            },
        )
        rows = extract_search_products(page_html)
        if args.sort == "latest":
            # 서버 응답 순서가 달라져도 최신순을 보장한다.
            rows.sort(
                key=lambda row: parse_sort_date(row.get("sortDate"))
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )

        print(f"[검색 {page}페이지] {len(rows)}개 결과 확인")

        new_product_count = 0
        for row in rows:
            product_id = row.get("seq")
            title = str(row.get("title") or "")

            if not product_id or product_id in seen_product_ids:
                continue

            seen_product_ids.add(product_id)
            new_product_count += 1

            # state=0은 판매 중인 상품이다.
            if row.get("state") != 0:
                continue
            if row.get("objectType") != "product":
                continue
            if not matches_query(title, args.query):
                continue

            yield row

        if new_product_count == 0 or not rows:
            break

        time.sleep(args.delay)


class JsonLdParser(HTMLParser):
    """상세 페이지의 JSON-LD 블록을 읽는다."""

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


# 상세 페이지 내부 데이터에서 추가로 읽는 필드.
# JSON-LD만으로는 알 수 없거나, JSON-LD 값이 실제와 다른 것들이다.
EMBEDDED_FIELD_KEYS = ("condition", "tradeType", "deliveryInfos")


def extract_json_value(text: str, key: str) -> Any | None:
    """`"key": {...}` 또는 `"key": [...]` 형태의 값을 찾아 파싱한다.

    문자열 리터럴 안의 괄호는 건너뛰므로 설명문에 괄호가 있어도 깨지지 않는다.
    """
    marker = f'"{key}":'
    start = text.find(marker)
    if start < 0:
        return None

    index = start + len(marker)
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] not in "[{":
        return None

    opener = text[index]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_string = False
    escaped = False

    for position in range(index, len(text)):
        char = text[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[index:position + 1])
                except json.JSONDecodeError:
                    return None
    return None


def extract_embedded_fields(page_html: str) -> dict[str, Any]:
    """상세 페이지 내부 데이터에서 JSON-LD로 알 수 없는 필드를 읽는다.

    - condition: JSON-LD의 offers.itemCondition은 미개봉 상품까지
      UsedCondition으로 고정되어 있어 실제 상태를 반영하지 못한다.
    - tradeType: 직거래/택배 여부를 플랫폼이 직접 명시한 값이다.
    - deliveryInfos: 실제 배송비. 검색 결과의 parcelFee는 0/1 플래그이며
      실제 배송비와 일치하지 않는다(parcelFee=0인데 배송비 4000원인 사례 확인).

    원본에서 읽지 못한 키는 결과에 넣지 않는다.
    """
    text = page_html.replace('\\"', '"')
    fields: dict[str, Any] = {}
    for key in EMBEDDED_FIELD_KEYS:
        value = extract_json_value(text, key)
        if value is not None:
            fields[key] = value
    return fields


def extract_detail(
    page_html: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    parser = JsonLdParser()
    parser.feed(page_html)

    product: dict[str, Any] = {}
    breadcrumbs: list[dict[str, Any]] = []

    for block in parser.blocks:
        try:
            data = json.loads(html.unescape(block))
        except json.JSONDecodeError:
            continue

        nodes = data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") == "Product":
                product = node
            elif node.get("@type") == "BreadcrumbList":
                breadcrumbs = [
                    item
                    for item in node.get("itemListElement", [])
                    if isinstance(item, dict)
                ]

    if not product:
        raise ValueError("상세 페이지에서 상품 구조화 데이터를 찾지 못했습니다.")

    return product, breadcrumbs


def get_product_detail(search_product: dict[str, Any]) -> dict[str, Any]:
    product_id = int(search_product["seq"])
    page_html = get_text(DETAIL_URL.format(product_id=product_id))
    product, breadcrumbs = extract_detail(page_html)

    title = str(product.get("name") or search_product.get("title") or "")
    raw_description = product.get("description")
    description = (
        mask_personal_info(str(raw_description))
        if raw_description is not None
        else None
    )
    offers = product.get("offers") or {}
    images = product.get("image") or []
    if isinstance(images, str):
        images = [images]

    # 판매자 내부 ID는 보존하지 않는다. 나머지 검색 필드는 중고나라의
    # 원래 필드명과 값을 유지해 플랫폼 데이터로 저장한다.
    joongna_search = {
        key: value
        for key, value in search_product.items()
        if key != "storeSeq"
    }

    # 상세 JSON-LD도 원래 구조를 보존하되 설명의 개인정보만 마스킹한다.
    json_ld_product = dict(product)
    if raw_description is not None:
        json_ld_product["description"] = description

    joongna_detail: dict[str, Any] = {
        "jsonLdProduct": json_ld_product,
        "jsonLdBreadcrumb": breadcrumbs,
    }

    # 원본에서 읽지 못한 키는 만들지 않는다.
    joongna_detail.update(extract_embedded_fields(page_html))

    return {
        "platform": "JOONGNA",
        "platformProductId": str(product_id),
        "url": DETAIL_URL.format(product_id=product_id),
        "common": {
            "title": title,
            "description": description,
            "price": offers.get("price", search_product.get("price")),
            "currency": offers.get("priceCurrency"),
            "images": [str(image) for image in images],
        },
        "joongna": {
            "search": joongna_search,
            "detail": joongna_detail,
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
        product_id = int(candidate["seq"])
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
