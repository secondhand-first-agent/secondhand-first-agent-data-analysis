"""세 중고거래 플랫폼이 공유하는 상품 JSON 스키마."""

from copy import deepcopy


SCHEMA_VERSION = "1.0.0"


PRODUCT_TEMPLATE = {
    "platform": None,
    "platformProductId": None,
    "url": None,
    "title": None,
    "productName": None,
    "description": None,
    "price": None,
    "originalPrice": None,
    "quantity": None,
    "saleStatus": None,
    "condition": None,
    "conditionLabel": None,
    "brand": None,
    "catalogProductId": None,
    "category": None,
    "categories": None,
    "attributes": None,
    "package": {
        "hasOriginalBox": None,
        "hasWarranty": None,
    },
    "trade": {
        "paymentType": None,
        "safetyPaymentAvailable": None,
        "transactionOfferAvailable": None,
        "buyerProtectionFeeRate": None,
        "shipping": {
            "available": None,
            "fee": None,
            "feePayer": None,
            "remoteAreaExtraFee": None,
            "freeShipping": None,
            "methods": None,
        },
        "inPerson": {
            "available": None,
            "locations": None,
        },
    },
    "metrics": {
        "favoriteCount": None,
        "viewCount": None,
        "chatCount": None,
    },
    "images": None,
    "seller": {
        "name": None,
        "profileId": None,
        "reviewRating": None,
        "reviewCount": None,
        "salesCount": None,
        "isProshop": None,
        "verified": None,
    },
    "createdAt": None,
    "updatedAt": None,
    "source": {
        "isSearchAd": None,
        "purchaseVerified": None,
        "isCrossPosted": None,
        "originalMarketName": None,
        "originalMarketProductUrl": None,
    },
}


def _merge_known_fields(target, values, path="product"):
    """템플릿에 정의된 필드만 재귀적으로 채운다."""

    for key, value in values.items():
        if key not in target:
            raise KeyError(f"공통 스키마에 없는 필드입니다: {path}.{key}")

        if isinstance(target[key], dict) and isinstance(value, dict):
            _merge_known_fields(target[key], value, f"{path}.{key}")
        else:
            target[key] = value


def build_product(values):
    """누락 필드를 null로 유지하는 공통 상품 객체를 만든다."""

    product = deepcopy(PRODUCT_TEMPLATE)
    _merge_known_fields(product, values)
    return product


def build_result(query, sort, collected_at, products, errors):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "query": query,
        "sort": sort,
        "collectedAt": collected_at,
        "count": len(products),
        "failedCount": len(errors),
        "products": products,
        "errors": errors,
    }


def shape(value):
    """값을 제외한 객체 키 구조를 반환한다. 테스트에서 사용한다."""

    if isinstance(value, dict):
        return {key: shape(child) for key, child in value.items()}
    return None
