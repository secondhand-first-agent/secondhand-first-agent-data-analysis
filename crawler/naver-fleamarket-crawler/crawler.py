import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common_schema import build_product, build_result


QUERY = "에어팟 프로3"
SORT = "latest"

MAX_PRODUCTS = 20
SEARCH_PAGE_SIZE = 20
MAX_SEARCH_PAGES = 5
REQUEST_DELAY_SECONDS = 1.0

API_BASE_URL = "https://apis.fleamarket.naver.com"
SEARCH_URL = API_BASE_URL + "/product/reader/v1/market-products/search"
DETAIL_PAGE_URL = "https://fleamarket.naver.com/market-products/{product_id}"
PROFILE_URL = API_BASE_URL + "/user/user-api/v1/profiles/{profile_id}"
TRANSACTION_URL = (
    API_BASE_URL
    + "/transaction/transaction-api/v1/profiles/{profile_id}/transaction-info"
)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "output" / "airpods_pro3.json"

# 완제품이 아닌 상품을 제외한다.
EXCLUDE_PATTERN = re.compile(
    r"왼쪽|오른쪽|한쪽|"
    r"유닛|낱개|단품|본체|"
    r"충전케이스|보호케이스|"
    r"이어팁|철가루|스티커|악세서리|액세서리|"
    r"부품|고장|파손|정크|"
    r"매입|삽니다|구합니다|구해요|대여",
    re.IGNORECASE,
)

CONDITION_MAP = {
    "NEW": ("NEW", "미사용 새 상품"),
    "ALMOST_NEW": ("LIKE_NEW", "사용감 거의 없음"),
    "USED": ("USED", "사용감 보통"),
    "USED_HEAVY": ("HEAVILY_USED", "사용감 많음"),
    "DAMAGED": ("DAMAGED", "고장/파손 상품"),
}

SALE_STATUS_MAP = {
    "ON_SALE": "SELLING",
    "RESERVED": "RESERVED",
    "SOLD_OUT": "SOLD_OUT",
}

session = requests.Session()
session.headers.update({
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://fleamarket.naver.com",
    "Referer": "https://fleamarket.naver.com/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
})


def get_response(url, params=None, max_retries=3):
    """일시적인 오류가 발생해도 최대 3번 재시도한다."""

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=20)
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            print(
                f"[요청 실패] {attempt}/{max_retries}: {error}",
                file=sys.stderr,
            )
            if attempt == max_retries:
                raise
            time.sleep(attempt * 2)


def get_json(url, params=None):
    response = get_response(url, params=params)
    try:
        payload = response.json()
    except ValueError as error:
        raise ValueError("JSON 응답이 아닙니다.") from error

    if payload.get("error"):
        detail = payload["error"].get("detail", "알 수 없는 API 오류")
        raise ValueError(detail)
    return payload.get("result", payload)


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


def milliseconds_to_iso(value):
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


class ScriptParser(HTMLParser):
    """Next.js 서버 렌더링 데이터가 담긴 script 태그를 수집한다."""

    def __init__(self):
        super().__init__()
        self.in_script = False
        self.current = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.in_script = True
            self.current = []

    def handle_data(self, data):
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.in_script:
            self.scripts.append("".join(self.current))
            self.in_script = False


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def decode_next_flight(script):
    prefix = "self.__next_f.push("
    if not script.startswith(prefix) or not script.endswith(")"):
        return None

    try:
        frame = json.loads(script[len(prefix):-1])
    except json.JSONDecodeError:
        return None

    if len(frame) < 2 or not isinstance(frame[1], str):
        return None

    encoded_payload = frame[1]
    if ":" not in encoded_payload:
        return None

    _, payload = encoded_payload.split(":", 1)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def extract_detail_data(page_html):
    """상세 HTML의 Next.js hydration 데이터에서 상품 객체를 찾는다."""

    parser = ScriptParser()
    parser.feed(html.unescape(page_html))

    for script in parser.scripts:
        if "marketProductInfo" not in script or "saleProduct" not in script:
            continue

        payload = decode_next_flight(script)
        if payload is None:
            continue

        for item in walk_dicts(payload):
            if "marketProductInfo" in item and "saleProduct" in item:
                return item

    raise ValueError("상세 페이지에서 상품 데이터를 찾지 못했습니다.")


def iter_search_products():
    seen_ids = set()

    for page in range(MAX_SEARCH_PAGES):
        start = page * SEARCH_PAGE_SIZE + 1
        result = get_json(
            SEARCH_URL,
            params={
                "query": QUERY,
                "start": start,
                "limit": SEARCH_PAGE_SIZE,
                "searchSortType": "DATE_DESC",
            },
        )

        rows = result.get("marketProducts", [])
        print(f"[검색 {page + 1}페이지] {len(rows)}개 결과 확인")

        for row in rows:
            product_id = row.get("marketProductId")
            title = row.get("title", "")

            if not product_id or product_id in seen_ids:
                continue
            seen_ids.add(product_id)

            if row.get("saleStatus") != "ON_SALE":
                continue
            if not is_target_product(title):
                continue

            yield row

        total = result.get("marketProductCount", 0)
        if not rows or start + len(rows) > total:
            break

        time.sleep(REQUEST_DELAY_SECONDS)


def get_seller(profile_id):
    if not profile_id:
        return {
            "name": None,
            "profileId": None,
            "reviewRating": None,
            "reviewCount": None,
            "salesCount": None,
            "isProshop": False,
            "verified": None,
        }

    profile_result = get_json(
        PROFILE_URL.format(profile_id=profile_id),
        params={"skipPersonalInfoDetection": "false"},
    )
    transaction_result = get_json(
        TRANSACTION_URL.format(profile_id=profile_id)
    )

    profile = profile_result.get("profile", {})
    auth = profile_result.get("auth", {})
    transaction_count = transaction_result.get("transactionCount", {})
    positive_rate = transaction_result.get("positiveReviewRate")
    review_detail = transaction_result.get("reviewDetail") or {}

    return {
        "name": profile.get("nickname"),
        "profileId": profile.get("profileId") or profile_id,
        "reviewRating": (
            round(positive_rate / 20, 1)
            if isinstance(positive_rate, (int, float))
            else None
        ),
        "reviewCount": review_detail.get("reviewCount"),
        "salesCount": transaction_count.get("count"),
        "isProshop": False,
        "verified": auth.get("hasCertificate"),
    }


def get_product_detail(search_product):
    product_id = search_product["marketProductId"]
    page_url = DETAIL_PAGE_URL.format(product_id=product_id)
    page_html = get_response(page_url).text
    detail = extract_detail_data(page_html)

    market_info = detail.get("marketProductInfo", {})
    product = detail.get("saleProduct", {})

    title = product.get("title") or search_product.get("title")
    raw_condition = product.get("productCondition")
    condition, condition_label = CONDITION_MAP.get(
        raw_condition,
        (raw_condition, raw_condition),
    )

    categories = [
        item.get("name")
        for item in product.get("productCategoryList", [])
        if item.get("name")
    ]
    images = [
        item.get("url")
        for item in product.get("productImages", [])
        if item.get("url")
    ]
    deliveries = product.get("saleProductDeliveries", [])
    regions = product.get("saleProductRegions", [])

    shipping_deliveries = [
        item
        for item in deliveries
        if item.get("deliveryType") == "PICKUP_DELIVERY"
    ]
    primary_shipping = (
        shipping_deliveries[0]
        if shipping_deliveries
        else {}
    )
    free_shipping = (
        all(
            item.get("deliveryFee", 0) == 0
            for item in shipping_deliveries
        )
        if shipping_deliveries
        else None
    )

    created_at = milliseconds_to_iso(
        market_info.get("createdAt")
        or search_product.get("createdAt")
    )
    updated_at = milliseconds_to_iso(
        product.get("lastModifiedAt")
        or product.get("modifiedAt")
        or market_info.get("createdAt")
    )

    seller = get_seller(market_info.get("sellerProfileId"))

    cross_posted = market_info.get("marketCrossPostedInfo") or {}

    return build_product({
        "platform": "NAVER_FLEAMARKET",
        "platformProductId": str(product_id),
        "url": page_url,
        "title": title,
        "productName": product.get("productName"),
        "description": mask_personal_info(product.get("content")),
        "price": product.get("price", search_product.get("price")),
        "originalPrice": product.get("price", search_product.get("price")),
        "quantity": 1,
        "saleStatus": SALE_STATUS_MAP.get(
            product.get("saleStatus"),
            product.get("saleStatus"),
        ),
        "condition": condition,
        "conditionLabel": condition_label,
        "brand": (product.get("brand") or {}).get("brandName"),
        "catalogProductId": product.get("productCatalogId"),
        "category": categories[-1] if categories else None,
        "categories": categories or None,
        "attributes": product.get("productProperties") or None,
        "package": {
            "hasOriginalBox": product.get("hasCase"),
            "hasWarranty": product.get("hasWarranty"),
        },
        "trade": {
            "paymentType": search_product.get("paymentType"),
            "safetyPaymentAvailable": (
                search_product.get("paymentType") == "FLEA_SAFETY"
                if search_product.get("paymentType") is not None
                else None
            ),
            "transactionOfferAvailable": product.get(
                "useTransactionOffer"
            ),
            "buyerProtectionFeeRate": detail.get("commission"),
            "shipping": {
                "available": bool(shipping_deliveries),
                "fee": primary_shipping.get("deliveryFee"),
                "feePayer": primary_shipping.get("payerType"),
                "remoteAreaExtraFee": primary_shipping.get(
                    "remoteDeliveryFee"
                ),
                "freeShipping": free_shipping,
                "methods": [
                    {
                        "type": item.get("deliveryType"),
                        "fee": item.get("deliveryFee"),
                        "feePayer": item.get("payerType"),
                        "remoteAreaExtraFee": item.get(
                            "remoteDeliveryFee"
                        ),
                    }
                    for item in shipping_deliveries
                ] or None,
            },
            "inPerson": {
                "available": bool(regions),
                "locations": [
                    {
                        "name": item.get("name"),
                        "regionCode": item.get("rcode"),
                    }
                    for item in regions
                    if item.get("name")
                ] or None,
            },
        },
        "metrics": {
            "favoriteCount": detail.get(
                "keepCount",
                search_product.get("keepCount"),
            ),
            "viewCount": None,
            "chatCount": None,
        },
        "images": images or None,
        "seller": seller,
        "createdAt": created_at,
        "updatedAt": updated_at,
        "source": {
            "isSearchAd": False,
            "purchaseVerified": search_product.get(
                "hasNpayPurchaseHistory"
            ),
            "isCrossPosted": (
                bool(
                    cross_posted.get("marketName")
                    or cross_posted.get("marketProductEndUrl")
                )
                if cross_posted
                else False
            ),
            "originalMarketName": cross_posted.get("marketName"),
            "originalMarketProductUrl": cross_posted.get(
                "marketProductEndUrl"
            ),
        },
    })


def crawl():
    print(f"[검색 시작] {QUERY}")
    print(f"[정렬 기준] {SORT}")

    collected_products = []
    errors = []

    for search_product in iter_search_products():
        product_id = search_product["marketProductId"]
        print(
            f"[{len(collected_products) + 1}/{MAX_PRODUCTS}] "
            f"{product_id} 상세 조회"
        )

        try:
            detail = get_product_detail(search_product)

            if not is_target_product(detail.get("title", "")):
                print(f"[제외] 다른 상품: {detail.get('title')}")
                continue
            if detail.get("saleStatus") != "SELLING":
                print(f"[제외] 판매 중 아님: {detail.get('title')}")
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
