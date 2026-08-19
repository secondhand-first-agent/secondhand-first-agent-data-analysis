import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common_schema import build_product, build_result


QUERY = "에어팟 프로3"

# "latest": 최신순
# "score": 정확도순
SORT = "latest"

MAX_PRODUCTS = 20
MAX_SEARCH_PAGES = 10
REQUEST_DELAY_SECONDS = 1.0

SEARCH_URL = (
    "https://api.bunjang.co.kr"
    "/api/search/v8/web/search"
)

DETAIL_URL = (
    "https://api.bunjang.co.kr"
    "/api/pms/v1/products/{product_id}/detail/web"
)

OUTPUT_PATH = Path(__file__).resolve().parent / "output" / "airpods_pro3.json"

# 완제품이 아닌 상품을 제외한다.
EXCLUDE_PATTERN = re.compile(
    r"왼쪽|오른쪽|한쪽|"
    r"유닛|낱개|단품|본체|"
    r"케이스|충전케이스|보호케이스|"
    r"이어팁|철가루|스티커|악세서리|액세서리|"
    r"부품|고장|정크|"
    r"매입|삽니다|구합니다|구해요|대여",
    re.IGNORECASE,
)

session = requests.Session()
session.headers.update({
    "Accept": "application/json",
    "User-Agent": (
        "SecondhandFirstAgent/0.1 "
        "(hackathon prototype; low-rate collector)"
    ),
    "Origin": "https://m.bunjang.co.kr",
    "Referer": "https://m.bunjang.co.kr/",
})


def get_json(url, params=None, max_retries=3):
    """일시적인 오류가 발생해도 최대 3번 재시도한다."""

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(
                url,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            return response.json()

        except (requests.RequestException, ValueError) as error:
            print(
                f"[요청 실패] {attempt}/{max_retries}: {error}",
                file=sys.stderr,
            )

            if attempt == max_retries:
                raise

            time.sleep(attempt * 2)

def normalize_title(title):
    """
    공백, 특수문자, 대소문자 차이를 제거한다.

    예:
    '에어팟 프로 3' -> '에어팟프로3'
    'AirPods Pro 3' -> 'airpodspro3'
    """

    if not title:
        return ""

    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        title.lower(),
    )


def is_target_product(title):
    """
    에어팟 프로3 완제품으로 판단되는 제목만 통과시킨다.
    """

    normalized = normalize_title(title)

    model_matched = (
        "에어팟프로3" in normalized
        or "airpodspro3" in normalized
    )

    if not model_matched:
        return False

    if EXCLUDE_PATTERN.search(title):
        return False

    return True

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


def make_image_urls(image_template, image_count):
    """{cnt}, {res} 형식의 이미지 URL을 실제 URL로 변환한다."""

    if not image_template:
        return []

    return [
        image_template
        .replace("{cnt}", str(index))
        .replace("{res}", "1200")
        for index in range(1, image_count + 1)
    ]


def iter_search_products():
    """
    검색 결과를 페이지 단위로 조회한다.

    광고와 중복 상품을 제거하고,
    에어팟 프로3 완제품 후보만 반환한다.
    """

    cursor = None
    previous_cursor = None
    seen_product_ids = set()

    for page in range(1, MAX_SEARCH_PAGES + 1):
        params = {
            "q": QUERY,
            "policyKey": "mw.product.keyword",
            "sort": SORT,
        }

        if cursor:
            params["cursor"] = cursor

        response = get_json(
            SEARCH_URL,
            params=params,
        )

        search_response = (
            response["data"]
            ["responses"]
            ["mainGrid"]
            ["searchResponse"]
        )

        rows = search_response.get("data", [])

        print(
            f"[검색 {page}페이지] "
            f"{len(rows)}개 결과 확인"
        )

        for row in rows:
            # 네이버 쇼핑 등 외부 광고를 제외한다.
            if row.get("type") != "PRODUCT":
                continue

            # 번개장터 내부 검색 광고도 제외한다.
            if row.get("ad") is True:
                continue

            product_id = row.get("pid")
            title = row.get("name", "")

            if not product_id:
                continue

            # 동일 상품이 광고와 일반 결과에 함께 나올 수 있다.
            if product_id in seen_product_ids:
                continue

            seen_product_ids.add(product_id)

            # 판매 중인 상품만 사용한다.
            if row.get("status") != "SELLING":
                continue

            # 에어팟 프로3 완제품 후보만 사용한다.
            if not is_target_product(title):
                continue

            yield row

        previous_cursor = cursor
        cursor = search_response.get("nextCursor")

        # 다음 페이지가 없거나 같은 커서가 반복되면 종료한다.
        if not cursor or cursor == previous_cursor:
            break

        time.sleep(REQUEST_DELAY_SECONDS)


def get_product_detail(product_id):
    response = get_json(
        DETAIL_URL.format(product_id=product_id)
    )

    data = response["data"]
    product = data["product"]
    shop = data.get("shop", {})
    trade = product.get("trade", {})
    geo_label = product.get("geoLabel")
    free_shipping = trade.get("freeShipping")
    in_person = trade.get("inPerson")
    product_specs = data.get("productSpecs", [])

    return build_product({
        "platform": "BUNJANG",
        "platformProductId": str(product["pid"]),
        "url": f"https://m.bunjang.co.kr/products/{product['pid']}",

        "title": product.get("name"),
        "productName": product.get("name"),
        "description": mask_personal_info(
            product.get("description")
        ),

        "price": product.get("price"),
        "originalPrice": product.get("originPrice"),
        "quantity": product.get("qty"),

        "saleStatus": product.get("saleStatus"),
        "condition": product.get("condition"),
        "conditionLabel": next(
            (
                spec.get("content")
                for spec in product_specs
                if spec.get("title") == "상품상태"
            ),
            None,
        ),

        "brand": (
            product.get("brand", {}).get("name")
            if product.get("brand")
            else None
        ),
        "category": product.get("category", {}).get("name"),
        "categories": [
            category.get("name")
            for category in product.get("categories", [])
        ] or None,
        "attributes": [
            {
                "name": spec.get("title"),
                "value": spec.get("content"),
            }
            for spec in product_specs
            if spec.get("title")
        ] or None,
        "trade": {
            "shipping": {
                # 무료배송이 명시된 경우에만 택배 가능을 확정한다.
                "available": True if free_shipping is True else None,
                "freeShipping": free_shipping,
            },
            "inPerson": {
                "available": in_person,
                # 위도·경도는 저장하지 않고 공개 지역명만 사용한다.
                "locations": (
                    [{"name": geo_label, "regionCode": None}]
                    if geo_label
                    else None
                ),
            },
        },
        "metrics": {
            "favoriteCount": product.get(
                "metrics", {}
            ).get("favoriteCount"),
            "viewCount": product.get(
                "metrics", {}
            ).get("viewCount"),
            "chatCount": product.get(
                "metrics", {}
            ).get("buntalkCount"),
        },

        "images": make_image_urls(
            product.get("imageUrl"),
            product.get("imageCount", 0),
        ),

        # 상점 이름은 필요할 때만 사용하고 UID는 저장하지 않는다.
        "seller": {
            "name": shop.get("name"),
            "profileId": None,
            "reviewRating": shop.get("reviewRating"),
            "reviewCount": shop.get("reviewCount"),
            "salesCount": shop.get("salesCount"),
            "isProshop": shop.get(
                "proshop", {}
            ).get("isProshop", False),
            "verified": None,
        },

        "createdAt": product.get("describedAt"),
        "updatedAt": product.get("updatedAt"),
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
        product_id = search_product["pid"]

        print(
            f"[{len(collected_products) + 1}/{MAX_PRODUCTS}] "
            f"{product_id} 상세 조회"
        )

        try:
            detail = get_product_detail(product_id)

            # 상세 조회 결과를 기준으로 한 번 더 검증한다.
            if not is_target_product(detail.get("title", "")):
                print(
                    f"[제외] 다른 상품: "
                    f"{detail.get('title')}"
                )
                continue

            # 상세 조회 시 이미 판매된 상품은 제외한다.
            if detail.get("saleStatus") != "SELLING":
                print(
                    f"[제외] 판매 중 아님: "
                    f"{detail.get('title')}"
                )
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

        # 정상 상품 20개가 모이면 즉시 종료한다.
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

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"[완료] {len(collected_products)}개 수집"
    )
    print(f"[저장 위치] {OUTPUT_PATH.resolve()}")

    if len(collected_products) < MAX_PRODUCTS:
        print(
            f"[주의] 조건에 맞는 상품이 "
            f"{MAX_PRODUCTS}개보다 적어 "
            f"{len(collected_products)}개만 저장했습니다."
        )

if __name__ == "__main__":
    crawl()
