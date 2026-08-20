"""N플리마켓에서 사용자가 입력한 상품을 검색해 JSON으로 저장한다.

예시:
    python3 naver_fleamarket_crawler.py "에어팟 프로3"
    python3 naver_fleamarket_crawler.py "아이폰 15 프로" --sort score
    python3 naver_fleamarket_crawler.py "닌텐도 스위치 OLED" --limit 10

주의:
    N플리마켓 웹의 공개 검색 API와 상세 페이지 데이터를 사용하므로
    사이트 변경 시 응답 구조가 달라질 수 있다. 낮은 요청 빈도로 사용한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


WEB_BASE_URL = "https://fleamarket.naver.com"
API_BASE_URL = "https://apis.fleamarket.naver.com/product/reader"
SEARCH_URL = f"{API_BASE_URL}/v1/market-products/search"
DETAIL_URL = f"{WEB_BASE_URL}/market-products/{{product_id}}"

SORT_VALUES = {
    "latest": "DATE_DESC",
    "score": "REL_DESC",
}

HEADERS = {
    "Accept": "application/json, text/html, application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": WEB_BASE_URL,
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
        description="N플리마켓에서 입력한 상품의 판매 글과 상세 정보를 수집합니다."
    )
    parser.add_argument(
        "query",
        help='검색할 상품명. 예: "아이폰 15 프로"',
    )
    parser.add_argument(
        "--sort",
        choices=("latest", "score"),
        default="latest",
        help="latest=최신순, score=관련도순 (기본값: latest)",
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
    return Path("output") / f"naver_fleamarket_{filename}.json"


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


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.loads(get_text(url, params=params))
    if not isinstance(data, dict):
        raise ValueError("JSON 응답이 객체 형식이 아닙니다.")
    if data.get("error"):
        raise ValueError(f"API 오류: {data['error']}")
    return data


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


def iter_search_products(args: argparse.Namespace) -> Iterator[dict[str, Any]]:
    start = 1
    seen_product_ids: set[str] = set()

    for page in range(1, args.max_pages + 1):
        response = get_json(
            SEARCH_URL,
            params={
                "query": args.query,
                "start": start,
                "limit": 20,
                "searchSortType": SORT_VALUES[args.sort],
            },
        )
        result = response.get("result") or {}
        rows = result.get("marketProducts") or []
        if not isinstance(rows, list):
            raise ValueError("검색 응답의 marketProducts가 배열이 아닙니다.")

        if args.sort == "latest":
            rows.sort(key=lambda row: row.get("createdAt") or 0, reverse=True)

        print(f"[검색 {page}페이지] {len(rows)}개 결과 확인")

        new_product_count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue

            product_id = str(row.get("marketProductId") or "")
            title = str(row.get("title") or "")
            if not product_id or product_id in seen_product_ids:
                continue

            seen_product_ids.add(product_id)
            new_product_count += 1

            if row.get("saleStatus") != "ON_SALE":
                continue
            if not matches_query(title, args.query):
                continue

            yield row

        item_count = int(result.get("itemCount") or len(rows))
        total_count = int(result.get("marketProductCount") or 0)
        start = int(result.get("start") or start) + item_count

        if new_product_count == 0 or not rows or item_count == 0:
            break
        if total_count and start > total_count:
            break

        time.sleep(args.delay)


class ScriptParser(HTMLParser):
    """상세 페이지의 인라인 Next.js 스크립트 내용을 읽는다."""

    def __init__(self) -> None:
        super().__init__()
        self.in_script = False
        self.current: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag == "script":
            self.in_script = True
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_script:
            self.blocks.append("".join(self.current))
            self.in_script = False


def walk_json(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def clean_next_value(value: Any) -> Any:
    """React 서버 컴포넌트의 $undefined 전송 표기만 제거한다."""

    if isinstance(value, dict):
        return {
            key: clean_next_value(child)
            for key, child in value.items()
            if child != "$undefined"
        }
    if isinstance(value, list):
        return [
            clean_next_value(child)
            for child in value
            if child != "$undefined"
        ]
    return value


def extract_detail_data(page_html: str) -> dict[str, Any]:
    parser = ScriptParser()
    parser.feed(page_html)

    for block in parser.blocks:
        marker = "self.__next_f.push("
        if marker not in block:
            continue

        argument = block.split(marker, 1)[1].rsplit(")", 1)[0]
        try:
            flight_entry = json.loads(argument)
        except json.JSONDecodeError:
            continue

        if (
            not isinstance(flight_entry, list)
            or len(flight_entry) < 2
            or not isinstance(flight_entry[1], str)
        ):
            continue

        _, separator, fragment = flight_entry[1].partition(":")
        if not separator:
            continue

        try:
            flight_value = json.loads(fragment)
        except json.JSONDecodeError:
            continue

        for node in walk_json(flight_value):
            if not isinstance(node, dict):
                continue
            queries = node.get("queries")
            if not isinstance(queries, list):
                continue

            for query in queries:
                if not isinstance(query, dict):
                    continue
                query_key = query.get("queryKey") or []
                state = query.get("state") or {}
                data = state.get("data")
                if (
                    isinstance(query_key, list)
                    and query_key[:1] == ["marketProducts"]
                    and isinstance(data, dict)
                    and data.get("marketProductInfo")
                    and data.get("saleProduct")
                ):
                    return clean_next_value(data)

    raise ValueError("상세 페이지에서 상품 상태 데이터를 찾지 못했습니다.")


# 지역 코드를 전체 주소로 바꾸는 네이버 지도 주소 조회 경로.
# 상품 상세는 읍/면/동 이름만 주고 상위 행정구역(regionName1~3)은 비어 있어,
# "중동"처럼 전국에 여러 개인 이름은 그대로는 위치를 특정할 수 없다.
# 이 주소는 302 Location 헤더로 전체 주소를 돌려주므로 본문을 받지 않는다.
REGION_ADDRESS_URL = "https://m.map.naver.com/search2/searchAddressById.naver?rcode={rcode}"

# 같은 지역이 여러 상품에 반복 등장하므로 조회 결과를 재사용한다.
_region_address_cache: dict[str, str | None] = {}


class _KeepRedirect(HTTPRedirectHandler):
    """리다이렉트를 따라가지 않고 Location 헤더만 보게 한다."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def resolve_region_address(rcode: str) -> str | None:
    """지역 코드로 전체 주소를 조회한다. 실패하면 None."""
    if not rcode:
        return None
    if rcode in _region_address_cache:
        return _region_address_cache[rcode]

    address: str | None = None
    opener = build_opener(_KeepRedirect)
    try:
        opener.open(
            Request(REGION_ADDRESS_URL.format(rcode=rcode), headers=HEADERS),
            timeout=15,
        )
    except HTTPError as error:
        if error.code in (301, 302, 303, 307, 308):
            location = error.headers.get("Location") or ""
            query = parse_qs(urlparse(location).query).get("query")
            address = query[0] if query else None
    except (URLError, OSError) as error:
        print(f"[주의] 지역 코드 {rcode} 주소 조회 실패: {error}", file=sys.stderr)

    _region_address_cache[rcode] = address
    return address


def attach_region_addresses(sale_product: dict[str, Any], delay: float) -> None:
    """각 거래 지역에 전체 주소를 덧붙인다. 조회에 실패한 지역은 건드리지 않는다."""
    for region in sale_product.get("saleProductRegions") or []:
        if not isinstance(region, dict):
            continue
        rcode = region.get("rcode")
        cached = rcode in _region_address_cache
        address = resolve_region_address(str(rcode) if rcode else "")
        if address:
            # 원본에 없는 파생 필드임을 이름으로 구분한다.
            region["resolvedFullAddress"] = address
        if not cached and delay:
            time.sleep(delay)


def get_product_detail(
    search_product: dict[str, Any],
    delay: float = 0.0,
) -> dict[str, Any]:
    product_id = str(search_product["marketProductId"])
    page_html = get_text(DETAIL_URL.format(product_id=product_id))
    detail = extract_detail_data(page_html)

    market_product_info = detail.get("marketProductInfo") or {}
    market_product_info.pop("sellerProfileId", None)

    sale_product = detail.get("saleProduct") or {}
    raw_description = sale_product.get("content")
    description = (
        mask_personal_info(str(raw_description))
        if raw_description is not None
        else None
    )
    if raw_description is not None:
        sale_product["content"] = description

    # 상세 응답의 regionName1~3이 비어 있어 동 이름만으로는 위치를 특정할 수 없다.
    # 지역 코드로 전체 주소를 따로 조회해 붙인다.
    attach_region_addresses(sale_product, delay)

    images = [
        str(image["url"])
        for image in sale_product.get("productImages") or []
        if isinstance(image, dict) and image.get("url")
    ]
    title = str(sale_product.get("title") or search_product.get("title") or "")

    return {
        "platform": "NAVER_FLEAMARKET",
        "platformProductId": product_id,
        "url": DETAIL_URL.format(product_id=product_id),
        "common": {
            "title": title,
            "description": description,
            "price": sale_product.get("price", search_product.get("price")),
            "currency": "KRW",
            "images": images,
        },
        "naverFleamarket": {
            "search": search_product,
            "detail": detail,
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
        product_id = str(candidate["marketProductId"])
        print(f"[{len(products) + 1}/{args.limit}] {product_id} 상세 조회")

        try:
            detail = get_product_detail(candidate, args.delay)
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
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"[실행 실패] {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
