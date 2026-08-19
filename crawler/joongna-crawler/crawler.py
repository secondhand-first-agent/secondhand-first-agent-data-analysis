import html
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common_schema import build_product, build_result


QUERY = "에어팟 프로3"
SORT = "latest"

MAX_PRODUCTS = 20
REQUEST_DELAY_SECONDS = 1.0

SEARCH_URL = "https://web.joongna.com/search/{query}"
DETAIL_URL = "https://web.joongna.com/product/{product_id}"

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "output" / "airpods_pro3.json"

# 완제품이 아닌 상품을 제외한다.
EXCLUDE_PATTERN = re.compile(
    r"왼쪽|오른쪽|한쪽|"
    r"유닛|낱개|단품|본체|"
    r"충전케이스|보호케이스|"
    r"이어팁|철가루|스티커|악세서리|액세서리|"
    r"부품|고장|정크|"
    r"매입|삽니다|구합니다|구해요|대여",
    re.IGNORECASE,
)

NEW_PATTERN = re.compile(r"미개봉|미사용|새상품|새제품", re.IGNORECASE)

session = requests.Session()
session.headers.update({
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Referer": "https://web.joongna.com/",
})


def get_text(url, params=None, max_retries=3):
    """일시적인 오류가 발생해도 최대 3번 재시도한다."""

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=20)
            response.raise_for_status()
            return response.text
        except requests.RequestException as error:
            print(
                f"[요청 실패] {attempt}/{max_retries}: {error}",
                file=sys.stderr,
            )
            if attempt == max_retries:
                raise
            time.sleep(attempt * 2)


def normalize_title(title):
    if not title:
        return ""
    return re.sub(r"[^0-9a-z가-힣]", "", title.lower())


def is_target_product(title):
    """에어팟 프로3 완제품으로 판단되는 제목만 통과시킨다."""

    normalized = normalize_title(title)
    model_matched = (
        "에어팟프로3" in normalized
        or "airpodspro3" in normalized
    )

    if not model_matched:
        return False
    return not EXCLUDE_PATTERN.search(title)


def mask_personal_info(text):
    """상품 설명에 포함될 수 있는 전화번호와 이메일을 마스킹한다."""

    if not text:
        return ""

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


class JsonLdParser(HTMLParser):
    """상세 페이지의 구조화된 상품 JSON을 읽는다."""

    def __init__(self):
        super().__init__()
        self.in_json_ld = False
        self.current = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attributes = dict(attrs)
        if attributes.get("type") == "application/ld+json":
            self.in_json_ld = True
            self.current = []

    def handle_data(self, data):
        if self.in_json_ld:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.in_json_ld:
            self.blocks.append("".join(self.current))
            self.in_json_ld = False


def decode_search_product(raw_product):
    """Next.js 스트림 안에서 이중 이스케이프된 상품 JSON을 복원한다."""

    decoded_text = json.loads(f'"{raw_product}"')
    return json.loads(decoded_text)


def extract_search_products(page_html):
    """검색 페이지에 포함된 공개 상품 목록을 추출한다."""

    pattern = re.compile(
        r'\{\\"seq\\":\d+,'
        r'\\"productPositionNo\\":.*?'
        r'\\"objectType\\":\\"product\\",'
        r'\\"wishYn\\":\d+\}',
        re.DOTALL,
    )

    products = []
    seen_ids = set()

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


def parse_sort_date(value):
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone(timedelta(hours=9))
        )
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def iter_search_products():
    url = SEARCH_URL.format(query=quote(QUERY, safe=""))
    page_html = get_text(url, params={"sort": "RECENT_SORT"})
    rows = extract_search_products(page_html)

    # 서버 응답 순서가 바뀌더라도 최신순을 보장한다.
    rows.sort(
        key=lambda row: parse_sort_date(row.get("sortDate")),
        reverse=True,
    )

    print(f"[검색] {len(rows)}개 결과 확인")

    for row in rows:
        title = row.get("title", "")

        # state=0은 판매 중인 일반 상품이다.
        if row.get("state") != 0:
            continue
        if row.get("objectType") != "product":
            continue
        if not is_target_product(title):
            continue

        yield row


def extract_detail(page_html):
    parser = JsonLdParser()
    parser.feed(page_html)

    product = {}
    categories = []

    for block in parser.blocks:
        try:
            data = json.loads(html.unescape(block))
        except json.JSONDecodeError:
            continue

        nodes = data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if node.get("@type") == "Product":
                product = node
            elif node.get("@type") == "BreadcrumbList":
                categories = [
                    item.get("name")
                    for item in node.get("itemListElement", [])
                    if item.get("position", 0) > 1 and item.get("name")
                ]

    if not product:
        raise ValueError("상세 페이지에서 상품 구조화 데이터를 찾지 못했습니다.")

    return product, categories


def get_product_detail(search_product):
    product_id = search_product["seq"]
    page_html = get_text(DETAIL_URL.format(product_id=product_id))
    product, categories = extract_detail(page_html)

    title = product.get("name") or search_product.get("title")
    condition = "NEW" if NEW_PATTERN.search(title or "") else "USED"
    sort_date = parse_sort_date(search_product.get("sortDate"))
    created_at = (
        sort_date.isoformat()
        if sort_date.year > 1
        else None
    )

    offers = product.get("offers", {})
    seller = offers.get("seller", {})
    images = product.get("image") or []
    if isinstance(images, str):
        images = [images]

    location_names = search_product.get("locationNames") or []
    location = (
        search_product.get("mainLocationName")
        or (location_names[-1] if location_names else None)
        or None
    )
    parcel_fee = search_product.get("parcelFee")
    has_parcel_fee = "parcelFee" in search_product

    return build_product({
        "platform": "JOONGNA",
        "platformProductId": str(product_id),
        "url": DETAIL_URL.format(product_id=product_id),
        "title": title,
        "productName": title,
        "description": mask_personal_info(product.get("description")),
        "price": offers.get("price", search_product.get("price")),
        "originalPrice": search_product.get("price"),
        "quantity": 1,
        "saleStatus": "SELLING",
        "condition": condition,
        "conditionLabel": (
            "새 상품 (미사용)" if condition == "NEW" else "중고"
        ),
        "brand": None,
        "category": categories[-1] if categories else None,
        "categories": categories or None,
        "trade": {
            "safetyPaymentAvailable": search_product.get("jnPayBadgeFlag"),
            "shipping": {
                "available": True if has_parcel_fee else None,
                "fee": parcel_fee if has_parcel_fee else None,
                "freeShipping": (
                    parcel_fee == 0 if has_parcel_fee else None
                ),
            },
            "inPerson": {
                # 지역명만으로 직거래 가능 여부를 확정하지 않는다.
                "available": None,
                "locations": (
                    [{"name": location, "regionCode": None}]
                    if location
                    else None
                ),
            },
        },
        "metrics": {
            "favoriteCount": search_product.get("wishCount"),
            "viewCount": None,
            "chatCount": search_product.get("chatCount"),
        },
        "images": images or None,
        "seller": {
            "name": seller.get("name"),
            "profileId": (
                str(search_product["storeSeq"])
                if search_product.get("storeSeq") is not None
                else None
            ),
            "reviewRating": None,
            "reviewCount": None,
            "salesCount": None,
            "isProshop": None,
            "verified": search_product.get("certifySellerFlag"),
        },
        "createdAt": created_at,
        "updatedAt": created_at,
        "source": {
            "isSearchAd": False,
        },
    })


def crawl():
    print(f"[검색 시작] {QUERY}")
    print(f"[정렬 기준] {SORT}")

    collected_products = []
    errors = []

    for search_product in iter_search_products():
        product_id = search_product["seq"]
        print(
            f"[{len(collected_products) + 1}/{MAX_PRODUCTS}] "
            f"{product_id} 상세 조회"
        )

        try:
            detail = get_product_detail(search_product)

            if not is_target_product(detail.get("title", "")):
                print(f"[제외] 다른 상품: {detail.get('title')}")
                continue

            collected_products.append(detail)
        except Exception as error:
            print(
                f"[상세 조회 실패] {product_id}: {error}",
                file=sys.stderr,
            )
            errors.append({
                "productId": str(product_id),
                "reason": str(error),
            })

        if len(collected_products) >= MAX_PRODUCTS:
            break

        time.sleep(REQUEST_DELAY_SECONDS)

    result = build_result(
        query=QUERY,
        sort=SORT,
        collected_at=datetime.now(timezone.utc).isoformat(),
        products=collected_products,
        errors=errors,
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(f"[완료] {len(collected_products)}개 수집")
    print(f"[저장 위치] {OUTPUT_PATH}")

    if len(collected_products) < MAX_PRODUCTS:
        print(
            f"[주의] 조건에 맞는 상품이 {MAX_PRODUCTS}개보다 적어 "
            f"{len(collected_products)}개만 저장했습니다."
        )


if __name__ == "__main__":
    crawl()
