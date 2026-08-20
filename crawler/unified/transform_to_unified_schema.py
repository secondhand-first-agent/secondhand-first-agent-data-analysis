"""
통합 스키마 변환기

번개장터 / 중고나라 / N플리마켓 크롤러가 만든 원본 JSON 3개를 읽어
공통 스키마(리서치 문서 4항목 기준)로 변환한다.

핵심 결정 사항 (팀 논의 결과):
1. 카테고리(category_path)는 이번 버전에서 통합 스키마에 포함하지 않는다.
   3사의 카테고리 체계(1단/3단/가변)를 매핑할 시간이 없어 완전히 제외한다.
2. 배송비(delivery_fee)는 플랫폼 원본을 raw에 그대로 보존하되,
   에이전트가 바로 쓸 수 있도록 부담 주체(payer)와 대표 금액
   (min_fee / home_delivery_fee), 정규화된 배송 수단(options)을 함께 제공한다.
   단일 금액으로 뭉개지는 않는다.
3. 상품상태(condition_level)는 6종으로 나눈다.
   NEW / LIKE_NEW / LIGHTLY_USED / USED / UNSPECIFIED / UNKNOWN
   - 번개장터·N플리마켓의 4등급 체계를 등급 위치로 대응시킨다.
   - HEAVILY_USED는 팀 논의 결과 USED로 통합한다.
   - 판매자 미기재(UNSPECIFIED)와 매핑 불가(UNKNOWN)는 구분한다.
4. 거래방식(trade_method)은 각 플랫폼이 명시한 값을 읽는다.
   중고나라는 상세 페이지의 tradeType을 사용한다.
5. 브랜드(brand)는 판매자 입력값이라 신뢰할 수 없어 스키마에서 제외한다.
6. 위치(location)는 객체로 제공하며 정밀도(precision)를 함께 표시한다.

이 스크립트는 값이 없는 곳에 임의의 0/false/추정값을 채우지 않는다.
판단이 불가능하면 null 또는 UNKNOWN으로 남긴다.
"""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------
# 상품상태 정규화
#
# 통합 값 6종:
#   NEW           새것
#   LIKE_NEW      거의 새것
#   LIGHTLY_USED  사용감 적음
#   USED          중고 (사용감 많음 + 세분화 정보 없는 경우)
#   UNSPECIFIED   판매자가 상태 등급을 지정하지 않음
#   UNKNOWN       매핑되지 않는 값이거나 필드 자체가 없음
#
# 번개장터와 N플리마켓은 등급 체계가 같고 이름만 다르다.
#   번개장터   NEW -> LIKE_NEW   -> LIGHTLY_USED -> HEAVILY_USED
#   N플리마켓  NEW -> ALMOST_NEW -> USED         -> HEAVILY_USED
# 등급의 위치로 대응시키므로 N플리마켓의 원본 "USED"는 LIGHTLY_USED가 되고,
# 원본 "HEAVILY_USED"가 통합 값 USED가 된다. 이름이 엇갈려 보이지만 의도된 것.
#
# HEAVILY_USED는 팀 논의 결과 USED로 통합한다. 그 결과 통합 값 USED에는
# "사용감 많음"과 "중고나라처럼 세분화 정보가 없는 중고"가 함께 들어간다.
# 구분이 필요하면 condition_raw를 참조할 것.
# ---------------------------------------------------------------------
BUNJANG_CONDITION_MAP = {
    "NEW": "NEW",
    "LIKE_NEW": "LIKE_NEW",
    "LIGHTLY_USED": "LIGHTLY_USED",
    "HEAVILY_USED": "USED",
    "UNDEFINED": "UNSPECIFIED",
}

NAVER_FLEAMARKET_CONDITION_MAP = {
    "NEW": "NEW",
    "ALMOST_NEW": "LIKE_NEW",
    "USED": "LIGHTLY_USED",
    "HEAVILY_USED": "USED",
}

# 중고나라는 새상품/중고 2단계만 제공해 사용 정도를 알 수 없다.
#   0 = 새상품 / 2 = 중고 (표본 확인)
#   1은 아직 관측되지 않았다. 팀 결정에 따라 UNSPECIFIED로 두고,
#   실제 값이 발견되면 그때 재확인한다.
JOONGNA_CONDITION_MAP = {
    0: "NEW",
    1: "UNSPECIFIED",
    2: "USED",
}


# 11번가는 검색 API에 상태 필드가 없고 상세 페이지의 "상품상태" 행에만 있다.
# 실측 35건에서 나온 값은 이 두 가지뿐이다. 리퍼 판매 상품도 "새상품"으로 나온다.
ELEVENST_CONDITION_MAP = {
    "새상품": "NEW",
    "중고상품": "USED",
}


def normalize_condition_bunjang(raw_condition):
    if raw_condition is None:
        return "UNKNOWN"
    return BUNJANG_CONDITION_MAP.get(raw_condition, "UNKNOWN")


def normalize_condition_naver_fleamarket(raw_condition):
    if raw_condition is None:
        return "UNKNOWN"
    return NAVER_FLEAMARKET_CONDITION_MAP.get(raw_condition, "UNKNOWN")


def joongna_raw_condition(detail):
    """상세 데이터에서 productCondition 원본값을 꺼낸다(없으면 None)."""
    condition = (detail or {}).get("condition") or {}
    return condition.get("productCondition")


def normalize_condition_joongna(_search, detail):
    """
    중고나라: 상세 페이지 내부 데이터의 condition.productCondition을 사용한다.
    jsonLdProduct.offers.itemCondition은 미개봉 상품까지 'UsedCondition'으로
    고정되어 있어 사용할 수 없다(표본 22건 전부 동일).
    """
    value = joongna_raw_condition(detail)
    if value is None:
        return "UNKNOWN"
    return JOONGNA_CONDITION_MAP.get(value, "UNKNOWN")


def condition_raw_text(value):
    """condition_raw는 문자열로 통일한다.

    플랫폼마다 문자열(번개장터·N플리마켓)과 정수(중고나라)가 섞여 있어
    그대로 두면 참조할 때 타입 분기가 필요하다. 판단은 condition_level로
    하고 이 필드는 추적·디버깅용이므로 문자열이 다루기 쉽다.
    """
    if value is None:
        return None
    return str(value)


# ---------------------------------------------------------------------
# 거래방식 추론
# ---------------------------------------------------------------------
def infer_trade_method_bunjang(product):
    """
    번개장터: freeShipping이 true면 무료배송이라 shippingSpecs가 없다.
    specs 유무만 보면 무료배송 상품에서 PARCEL이 누락되므로 함께 확인한다.
    """
    methods = []
    trade = product.get("trade") or {}
    if trade.get("freeShipping") is True or trade.get("shippingSpecs"):
        methods.append("PARCEL")
    if trade.get("inPerson") is True:
        methods.append("MEET")
    return methods


def infer_trade_method_naver_fleamarket(sale_product):
    methods = []
    deliveries = sale_product.get("saleProductDeliveries") or []
    regions = sale_product.get("saleProductRegions") or []
    if deliveries:
        methods.append("PARCEL")
    if regions:
        methods.append("MEET")
    return methods


def infer_trade_method_joongna(detail):
    """
    중고나라: 상세 페이지의 tradeType이 직거래/택배 여부를 직접 명시한다.
    다른 두 플랫폼처럼 배송/지역 정보 유무로 유추하는 것이 아니라
    플랫폼이 지정한 값을 그대로 읽는다(표본 15건 전부 필드 존재).
    isPickup(편의점 픽업)은 통합 스키마에 대응 값이 없어 반영하지 않는다.
    """
    trade_type = (detail or {}).get("tradeType") or {}
    methods = []
    if trade_type.get("isPost") is True:
        methods.append("PARCEL")
    if trade_type.get("isMeet") is True:
        methods.append("MEET")
    return methods


# ---------------------------------------------------------------------
# 배송비
#
# 원본(raw)은 그대로 보존하되, 에이전트가 바로 쓸 수 있도록 배송 수단을
# 정규화하고 두 가지 대표 금액을 미리 계산해 둔다.
#
#   min_fee            전체 최저 배송비
#   home_delivery_fee  편의점 픽업이 필요 없는 수단 중 최저 배송비
#
# 편의점 택배(반값/알뜰)가 가장 싸지만 주변에 해당 편의점이 없는 사용자에게는
# 선택지가 아니다. 최저가만으로 비교하면 그런 사용자에게 실제보다 싸 보이므로
# 두 값을 나누어 제공한다. requires_pickup_point로 개별 필터링도 가능하다.
# ---------------------------------------------------------------------
# (플랫폼, 원본 코드) -> (정규화 수단, 택배사, 픽업 장소 방문 필요 여부)
DELIVERY_METHOD_MAP = {
    ("BUNJANG", "DEFAULT"):       ("STANDARD", None, False),
    ("BUNJANG", "GS_HALF_PRICE"): ("CONVENIENCE_STORE", "GS25", True),
    ("BUNJANG", "CU_THRIFTY"):    ("CONVENIENCE_STORE", "CU", True),
    # 중고나라 deliveryType: 0=일반택배, 1=CU 반값택배, 2=GS 반값택배.
    #   세 값이 함께 나온 글의 화면 표기와 금액이 정확히 대응해 확정했다.
    #     일반택배 5,000원 / CU 반값택배 2,700원 / GS 반값택배 2,800원
    ("JOONGNA", 0):               ("STANDARD", None, False),
    ("JOONGNA", 1):               ("CONVENIENCE_STORE", "CU", True),
    ("JOONGNA", 2):               ("CONVENIENCE_STORE", "GS25", True),
    # N플리마켓 PICKUP_DELIVERY는 3,600원 정액이라 플랫폼 픽업 서비스로 판단.
    # 화면 라벨로 확정하지는 못했다.
    ("NAVER_FLEAMARKET", "DIRECT_DELIVERY"): ("STANDARD", None, False),
    ("NAVER_FLEAMARKET", "PICKUP_DELIVERY"): ("CONVENIENCE_STORE", None, True),
}

# 판매자가 배송비를 부담할 때 쓰는 단일 옵션. 다른 수단과 형태를 맞춘다.
FREE_DELIVERY_OPTION = {
    "method": "FREE",
    "carrier": None,
    "requires_pickup_point": False,
    "fee": 0,
    "remote_fee": None,
    "raw_code": None,
}


def delivery_option(platform, raw_code, fee, remote_fee=None):
    """플랫폼 원본 코드를 정규화된 배송 수단 한 건으로 변환한다."""
    method, carrier, requires_pickup = DELIVERY_METHOD_MAP.get(
        (platform, raw_code), ("UNKNOWN", None, False)
    )
    return {
        "method": method,
        "carrier": carrier,
        "requires_pickup_point": requires_pickup,
        "fee": fee,
        "remote_fee": remote_fee,
        "raw_code": raw_code,
    }


def delivery_result(payer, options, raw):
    """옵션 목록에서 대표 금액 두 개를 계산해 delivery_fee를 완성한다."""
    fees = [o["fee"] for o in options if o["fee"] is not None]
    home_fees = [
        o["fee"] for o in options
        if o["fee"] is not None and not o["requires_pickup_point"]
    ]
    return {
        "status": "AVAILABLE",
        "payer": payer,
        "min_fee": min(fees) if fees else None,
        # 편의점 택배만 가능하면 None. 픽업이 어려운 사용자에게는 선택지가 없다.
        "home_delivery_fee": min(home_fees) if home_fees else None,
        "options": options,
        "raw": raw,
    }


def delivery_unavailable():
    return {
        "status": "NOT_AVAILABLE",
        "payer": None,
        "min_fee": None,
        "home_delivery_fee": None,
        "options": [],
        "raw": None,
    }


def delivery_free(raw):
    return delivery_result("SELLER", [dict(FREE_DELIVERY_OPTION)], raw)



def delivery_fee_bunjang(product):
    """
    번개장터: freeShipping이 true면 판매자 부담(무료배송)이며,
    이때 shippingSpecs는 아예 존재하지 않는다. specs 유무만으로 판단하면
    무료배송 상품이 '정보 없음'으로 잘못 처리되므로 먼저 확인한다.
    """
    trade = product.get("trade") or {}
    if trade.get("freeShipping") is True:
        return delivery_free({"freeShipping": True})

    shipping_specs = trade.get("shippingSpecs") or {}
    if not shipping_specs:
        return delivery_unavailable()

    options = [
        delivery_option("BUNJANG", code, (spec or {}).get("fee"))
        for code, spec in shipping_specs.items()
    ]
    return delivery_result("BUYER", options, shipping_specs)


def delivery_fee_joongna(search, detail):
    """
    중고나라: parcelFee는 금액이 아니라 '배송비 포함 여부' 플래그다.
      parcelFee == 1  -> 배송비 포함(판매자 부담). 화면에 '배송비 포함/무료배송'
                         으로 표시되며 deliveryInfos는 존재하지 않는다.
      parcelFee == 0  -> deliveryInfos에 구매자가 낼 금액이 들어 있다.
                         배열이 비어 있으면 택배 거래가 아니다.
    표본 15건에서 두 값이 어긋나는 사례는 없었다.
    """
    if search.get("parcelFee") == 1:
        return delivery_free({"parcelFee": 1})

    infos = (detail or {}).get("deliveryInfos")
    if not infos:
        return delivery_unavailable()

    options = [
        delivery_option("JOONGNA", info.get("deliveryType"), info.get("deliveryPrice"))
        for info in infos
    ]
    return delivery_result("BUYER", options, infos)


def delivery_fee_naver_fleamarket(sale_product):
    """
    N플리마켓: payerType이 부담 주체를 직접 명시한다(BUYER / SELLER).
    배송 수단이 여러 개이고 부담 주체가 서로 다르면 단정하지 않고 None을 둔다.
    """
    deliveries = sale_product.get("saleProductDeliveries") or []
    if not deliveries:
        return delivery_unavailable()

    payers = {d.get("payerType") for d in deliveries if d.get("payerType")}
    payer = payers.pop() if len(payers) == 1 else None

    # 판매자가 전액 부담하면 구매자가 낼 금액이 없으므로 FREE로 통일한다.
    if payer == "SELLER":
        return delivery_free(deliveries)

    options = [
        delivery_option(
            "NAVER_FLEAMARKET",
            d.get("deliveryType"),
            d.get("deliveryFee"),
            d.get("remoteDeliveryFee"),
        )
        for d in deliveries
    ]
    return delivery_result(payer, options, deliveries)


# ---------------------------------------------------------------------
# 위치
#
# 세 플랫폼 모두 좌표를 제공하지 않고 행정동 텍스트만 준다. 거리 계산은
# 별도 지오코딩 단계에서 채우도록 coordinates 자리만 만들어 둔다.
#
# 정밀도가 플랫폼마다 다르다는 점이 중요하다.
#   FULL       시도/시군구/읍면동이 모두 있음 (번개장터, 중고나라)
#   DONG_ONLY  동 이름만 있음 (N플리마켓). 동명이 전국에 여러 개일 수 있어
#              지오코딩이 모호하다. rcode가 함께 오지만 네이버 자체 코드라
#              공개 행정구역 데이터와 조인되지 않는다.
#   NONE       위치 정보 없음
#
# 거리 점수를 매길 때 precision을 무시하면 특정 플랫폼이 체계적으로
# 유리하거나 불리해지므로 반드시 함께 읽어야 한다.
# ---------------------------------------------------------------------
def clean_location(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def location_region(name, full_address=None, code=None):
    return {
        "name": clean_location(name),
        "full_address": clean_location(full_address),
        "code": code,
    }


def build_location(regions, precision):
    """거래 가능 지역 목록을 통합 스키마의 location 객체로 만든다.

    regions가 여러 개면(N플리마켓은 최대 3개) 대표값은 첫 번째를 쓰되
    전체 목록을 보존한다. 거리 점수는 가장 가까운 지역 기준으로 계산해야 한다.
    """
    regions = [r for r in regions if r["name"] or r["full_address"]]
    if not regions:
        return {
            "name": None,
            "full_address": None,
            "precision": "NONE",
            "regions": [],
            "coordinates": None,
        }
    return {
        "name": regions[0]["name"],
        "full_address": regions[0]["full_address"],
        "precision": precision,
        "regions": regions,
        # 크롤링 시점에는 알 수 없다. 지오코딩 단계에서 채운다.
        "coordinates": None,
    }


def location_bunjang(product):
    address = clean_location((product.get("geo") or {}).get("address"))
    if not address:
        return build_location([], "NONE")
    return build_location([location_region(address, address)], "FULL")


def location_joongna(search):
    names = search.get("locationNames") or []
    main = clean_location(search.get("mainLocationName"))
    regions = [location_region(main or full, full) for full in names]
    return build_location(regions, "FULL")


def location_naver_fleamarket(sale_product):
    """N플리마켓: 상세 응답은 동 이름과 내부 지역 코드만 준다.

    크롤러가 지역 코드로 전체 주소를 조회해 resolvedFullAddress에 붙여 두면
    다른 두 플랫폼과 같은 FULL 정밀도가 된다. 조회가 실패해 하나라도 빠져
    있으면 DONG_ONLY로 낮춰 거리 계산에서 과신하지 않게 한다.
    """
    raw_regions = sale_product.get("saleProductRegions") or []
    regions = [
        location_region(r.get("name"), r.get("resolvedFullAddress"), r.get("rcode"))
        for r in raw_regions
    ]
    resolved = [r for r in regions if r["full_address"]]
    precision = "FULL" if regions and len(resolved) == len(regions) else "DONG_ONLY"
    return build_location(regions, precision)


# ---------------------------------------------------------------------
# 브랜드는 통합 스키마에서 제외한다.
#
# N플리마켓만 brand를 제공하는데 판매자가 직접 입력하는 값이라 신뢰할 수
# 없다(샤넬 가방 게시글의 brandName이 '안'으로 등록된 사례 확인).
# 세 플랫폼 공통으로 의미가 같은 필드가 아니므로 brand /
# brand_normalized를 스키마에서 완전히 배제한다.
# ---------------------------------------------------------------------


# ---------------------------------------------------------------------
# 플랫폼별 변환기
# ---------------------------------------------------------------------
def normalize_condition_elevenst(detail):
    """11번가 상세 페이지의 "상품상태" 행을 통합 상태값으로 바꾼다.

    행 자체가 없으면 UNKNOWN이다. 새상품 마켓이라고 NEW로 단정하면
    실제로 섞여 있는 중고 상품을 새것으로 잘못 읽는다.
    """
    return ELEVENST_CONDITION_MAP.get(detail.get("productStatus"), "UNKNOWN")


ELEVENST_FEE_RE = re.compile(r"([\d,]+)\s*원")


def delivery_fee_elevenst(search):
    """검색 결과의 deliveryDescription을 배송비로 해석한다.

    실측 값은 "무료" 또는 "2,500원" 형태다. 11번가는 통신판매 중개라
    편의점 픽업이 없고 배송 수단은 일반 택배 하나뿐이다.
    """
    raw = search.get("deliveryDescription")

    if raw == "무료":
        return delivery_free(raw)

    if isinstance(raw, str):
        matched = ELEVENST_FEE_RE.search(raw)
        if matched:
            fee = int(matched.group(1).replace(",", ""))
            option = {
                "method": "STANDARD",
                "carrier": None,
                "requires_pickup_point": False,
                "fee": fee,
                "remote_fee": None,
                "raw_code": raw,
            }
            # 금액이 따로 표시되면 구매자가 낸다.
            return delivery_result("BUYER", [option], raw)

    # 해석하지 못한 값을 0원이나 무료로 채우지 않는다.
    return delivery_unavailable()


def location_elevenst():
    """11번가는 직거래가 없어 위치 정보 자체가 의미 없다.

    판매자 주소는 사업자 정보일 뿐 만나는 장소가 아니므로 비워 둔다.
    거리 점수 계산에서 제외되어야 한다.
    """
    return build_location([], "NONE")


def transform_elevenst(raw_file, collected_at_fallback):
    out = []
    for item in raw_file.get("products", []):
        common = item.get("common", {})
        elevenst = item.get("elevenst", {})
        search = elevenst.get("search", {})
        detail = elevenst.get("detail", {})

        out.append({
            "platform": item.get("platform"),
            "platform_product_id": str(item.get("platformProductId")),
            "url": item.get("url"),
            "title": common.get("title"),
            "price": common.get("price"),
            "currency": common.get("currency"),
            "description": common.get("description"),
            "images": common.get("images", []),
            "condition_level": normalize_condition_elevenst(detail),
            "condition_raw": condition_raw_text(detail.get("productStatus")),
            # 오픈마켓이라 택배만 가능하다. 직거래 선택지가 없다.
            "trade_method": ["PARCEL"],
            "delivery_fee": delivery_fee_elevenst(search),
            "location": location_elevenst(),
            "collected_at": raw_file.get("collectedAt", collected_at_fallback),
        })
    return out


def transform_bunjang(raw_file, collected_at_fallback):
    out = []
    for item in raw_file.get("products", []):
        common = item.get("common", {})
        product = item.get("bunjang", {}).get("detail", {}).get("product", {})

        out.append({
            "platform": item.get("platform"),
            "platform_product_id": str(item.get("platformProductId")),
            "url": item.get("url"),
            "title": common.get("title"),
            "price": common.get("price"),
            "currency": common.get("currency"),
            "description": common.get("description"),
            "images": common.get("images", []),
            "condition_level": normalize_condition_bunjang(product.get("condition")),
            "condition_raw": condition_raw_text(product.get("condition")),
            "trade_method": infer_trade_method_bunjang(product),
            "delivery_fee": delivery_fee_bunjang(product),
            "location": location_bunjang(product),
            "collected_at": raw_file.get("collectedAt", collected_at_fallback),
        })
    return out


def transform_joongna(raw_file, collected_at_fallback):
    out = []
    for item in raw_file.get("products", []):
        common = item.get("common", {})
        joongna = item.get("joongna", {})
        search = joongna.get("search", {})
        detail = joongna.get("detail", {})

        out.append({
            "platform": item.get("platform"),
            "platform_product_id": str(item.get("platformProductId")),
            "url": item.get("url"),
            "title": common.get("title"),
            "price": common.get("price"),
            "currency": common.get("currency"),
            "description": common.get("description"),
            "images": common.get("images", []),
            "condition_level": normalize_condition_joongna(search, detail),
            "condition_raw": condition_raw_text(joongna_raw_condition(detail)),
            "trade_method": infer_trade_method_joongna(detail),
            "delivery_fee": delivery_fee_joongna(search, detail),
            "location": location_joongna(search),
            "collected_at": raw_file.get("collectedAt", collected_at_fallback),
        })
    return out


def transform_naver_fleamarket(raw_file, collected_at_fallback):
    out = []
    for item in raw_file.get("products", []):
        common = item.get("common", {})
        sale_product = (
            item.get("naverFleamarket", {}).get("detail", {}).get("saleProduct", {})
        )
        out.append({
            "platform": item.get("platform"),
            "platform_product_id": str(item.get("platformProductId")),
            "url": item.get("url"),
            "title": common.get("title"),
            "price": common.get("price"),
            "currency": common.get("currency"),
            "description": common.get("description"),
            "images": common.get("images", []),
            "condition_level": normalize_condition_naver_fleamarket(
                sale_product.get("productCondition")
            ),
            "condition_raw": condition_raw_text(sale_product.get("productCondition")),
            "trade_method": infer_trade_method_naver_fleamarket(sale_product),
            "delivery_fee": delivery_fee_naver_fleamarket(sale_product),
            "location": location_naver_fleamarket(sale_product),
            "collected_at": raw_file.get("collectedAt", collected_at_fallback),
        })
    return out


# ---------------------------------------------------------------------
# 실행부
# ---------------------------------------------------------------------
def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse_args():
    parser = argparse.ArgumentParser(
        description="크롤러 원본 JSON 3개를 통합 스키마로 변환합니다."
    )
    parser.add_argument("--bunjang", type=Path, required=True, help="번개장터 크롤링 결과 JSON")
    parser.add_argument("--joongna", type=Path, required=True, help="중고나라 크롤링 결과 JSON")
    parser.add_argument(
        "--naver-fleamarket", type=Path, required=True, help="N플리마켓 크롤링 결과 JSON"
    )
    parser.add_argument(
        "--elevenst", type=Path, help="11번가 크롤링 결과 JSON (선택)"
    )
    parser.add_argument("--output", type=Path, required=True, help="통합 결과 JSON 경로")
    return parser.parse_args()


def build_unified(bunjang_raw, joongna_raw, naver_raw, elevenst_raw=None):
    """원본 3종을 읽어 통합 결과 객체를 만든다."""
    now_fallback = datetime.now(timezone.utc).isoformat()

    unified = []
    unified += transform_bunjang(bunjang_raw, now_fallback)
    unified += transform_joongna(joongna_raw, now_fallback)
    unified += transform_naver_fleamarket(naver_raw, now_fallback)
    if elevenst_raw is not None:
        unified += transform_elevenst(elevenst_raw, now_fallback)

    # 검색어는 세 파일 모두 동일해야 하지만, 비어 있는 파일이 있을 수 있어
    # 값이 있는 첫 번째 것을 쓴다.
    sources = [bunjang_raw, joongna_raw, naver_raw]
    if elevenst_raw is not None:
        sources.append(elevenst_raw)
    query = next((raw.get("query") for raw in sources if raw.get("query")), None)

    return {
        "query": query,
        "generatedAt": now_fallback,
        "sourceCounts": {
            "BUNJANG": len(bunjang_raw.get("products", [])),
            "JOONGNA": len(joongna_raw.get("products", [])),
            "NAVER_FLEAMARKET": len(naver_raw.get("products", [])),
            **(
                {"ELEVENST": len(elevenst_raw.get("products", []))}
                if elevenst_raw is not None
                else {}
            ),
        },
        "count": len(unified),
        "items": unified,
    }


def main():
    args = parse_args()

    result = build_unified(
        load(args.bunjang),
        load(args.joongna),
        load(args.naver_fleamarket),
        load(args.elevenst) if args.elevenst else None,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"완료: {result['count']}건 -> {args.output}")


if __name__ == "__main__":
    main()
