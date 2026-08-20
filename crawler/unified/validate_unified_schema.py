"""
통합 스키마 검증기

transform_to_unified_schema.py가 만든 unified_*.json을 읽어
필드 타입·enum 값·플랫폼별 분포를 점검하고 리포트를 출력한다.

사용법:
    python3 validate_unified_schema.py unified_에어팟_프로3.json
    python3 validate_unified_schema.py unified_*.json  # 여러 파일 동시 검증 가능
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime

VALID_CONDITION = {
    "NEW",           # 새것
    "LIKE_NEW",      # 거의 새것
    "LIGHTLY_USED",  # 사용감 적음
    "USED",          # 중고 (사용감 많음 + 세분화 정보 없음)
    "UNSPECIFIED",   # 판매자가 등급 미기재
    "UNKNOWN",       # 매핑 불가 / 필드 누락
}
VALID_TRADE_METHOD = {"PARCEL", "MEET"}
VALID_DELIVERY_STATUS = {"AVAILABLE", "NOT_AVAILABLE"}
# 배송비 부담 주체. 판단할 수 없으면 None을 허용한다.
VALID_DELIVERY_PAYER = {"SELLER", "BUYER", None}
VALID_DELIVERY_METHOD = {"FREE", "STANDARD", "CONVENIENCE_STORE", "UNKNOWN"}
# 위치 정밀도. 거리 점수를 매길 때 반드시 함께 읽어야 한다.
VALID_LOCATION_PRECISION = {"FULL", "DONG_ONLY", "NONE"}
VALID_PLATFORMS = {"BUNJANG", "JOONGNA", "NAVER_FLEAMARKET", "ELEVENST"}

REQUIRED_STRING_FIELDS = ["platform", "platform_product_id", "url", "title", "currency"]


def check_type(value, expected_types, field_name, item_id, errors):
    if value is not None and not isinstance(value, expected_types):
        errors.append(
            f"[{item_id}] {field_name}: 타입 오류 "
            f"(예상 {expected_types}, 실제 {type(value).__name__})"
        )


def validate_item(item, errors, warnings):
    item_id = f"{item.get('platform')}:{item.get('platform_product_id')}"

    # 필수 문자열 필드
    for f in REQUIRED_STRING_FIELDS:
        if not item.get(f):
            errors.append(f"[{item_id}] {f}: 값이 비어있음(필수 필드)")
        else:
            check_type(item.get(f), str, f, item_id, errors)

    # platform enum
    if item.get("platform") not in VALID_PLATFORMS:
        errors.append(f"[{item_id}] platform: 알 수 없는 값 '{item.get('platform')}'")

    # url 형식
    url = item.get("url")
    if url and not str(url).startswith("http"):
        errors.append(f"[{item_id}] url: http로 시작하지 않음 -> {url}")

    # price
    price = item.get("price")
    check_type(price, (int, float), "price", item_id, errors)
    if isinstance(price, (int, float)) and price < 0:
        errors.append(f"[{item_id}] price: 음수 값 {price}")

    # price_range — 옵션에 따라 가격이 달라지는 상품만 값이 있다
    pr = item.get("price_range")
    if pr is not None:
        if not isinstance(pr, dict):
            errors.append(f"[{item_id}] price_range: 객체가 아님")
        else:
            low, high = pr.get("min"), pr.get("max")
            if not isinstance(low, int) or not isinstance(high, int):
                errors.append(f"[{item_id}] price_range: min/max가 정수가 아님")
            else:
                if high <= low:
                    errors.append(
                        f"[{item_id}] price_range: max가 min보다 크지 않음 "
                        f"({low} ~ {high}). 가격이 변하지 않으면 null이어야 한다"
                    )
                # 표시가는 옵션 최저가와 같아야 한다. 어긋나면 어느 쪽이
                # 진짜 하한인지 알 수 없어 총 지불액 비교가 무너진다.
                if isinstance(price, int) and price != low:
                    errors.append(
                        f"[{item_id}] price_range: price({price})와 "
                        f"min({low})이 다름"
                    )

    # currency
    if item.get("currency") not in (None, "KRW"):
        warnings.append(f"[{item_id}] currency: KRW가 아님 -> {item.get('currency')}")

    # description
    check_type(item.get("description"), str, "description", item_id, errors)

    # images
    images = item.get("images")
    check_type(images, list, "images", item_id, errors)
    if isinstance(images, list):
        for im in images:
            if not isinstance(im, str):
                errors.append(f"[{item_id}] images: 리스트 안에 문자열이 아닌 값 존재")
                break

    # condition_level enum
    cl = item.get("condition_level")
    if cl not in VALID_CONDITION:
        errors.append(f"[{item_id}] condition_level: 정의되지 않은 값 '{cl}'")

    # trade_method enum
    tm = item.get("trade_method")
    check_type(tm, list, "trade_method", item_id, errors)
    if isinstance(tm, list):
        for v in tm:
            if v not in VALID_TRADE_METHOD:
                errors.append(f"[{item_id}] trade_method: 정의되지 않은 값 '{v}'")

    # delivery_fee
    df = item.get("delivery_fee")
    if not isinstance(df, dict):
        errors.append(f"[{item_id}] delivery_fee: dict가 아님")
    else:
        status = df.get("status")
        if status not in VALID_DELIVERY_STATUS:
            errors.append(f"[{item_id}] delivery_fee.status: 정의되지 않은 값 '{status}'")
        if status == "AVAILABLE" and df.get("raw") is None:
            errors.append(f"[{item_id}] delivery_fee: status=AVAILABLE인데 raw가 None")
        if status == "NOT_AVAILABLE" and df.get("raw") is not None:
            warnings.append(f"[{item_id}] delivery_fee: status=NOT_AVAILABLE인데 raw가 존재함")

        # payer: 배송비를 누가 부담하는지. 판단 불가면 None.
        payer = df.get("payer")
        if payer not in VALID_DELIVERY_PAYER:
            errors.append(f"[{item_id}] delivery_fee.payer: 정의되지 않은 값 '{payer}'")
        if status == "NOT_AVAILABLE" and payer is not None:
            errors.append(f"[{item_id}] delivery_fee: status=NOT_AVAILABLE인데 payer가 {payer}")
        if status == "AVAILABLE" and payer is None:
            warnings.append(f"[{item_id}] delivery_fee: status=AVAILABLE인데 payer를 특정하지 못함")

        # options / 대표 금액 정합성
        options = df.get("options")
        check_type(options, list, "delivery_fee.options", item_id, errors)
        if isinstance(options, list):
            for o in options:
                if not isinstance(o, dict):
                    errors.append(f"[{item_id}] delivery_fee.options: dict가 아닌 항목 존재")
                    continue
                if o.get("method") not in VALID_DELIVERY_METHOD:
                    errors.append(
                        f"[{item_id}] delivery_fee.options.method: "
                        f"정의되지 않은 값 '{o.get('method')}'"
                    )
                if not isinstance(o.get("requires_pickup_point"), bool):
                    errors.append(
                        f"[{item_id}] delivery_fee.options.requires_pickup_point: 불리언이 아님"
                    )

            fees = [o.get("fee") for o in options
                    if isinstance(o, dict) and o.get("fee") is not None]
            home = [o.get("fee") for o in options
                    if isinstance(o, dict) and o.get("fee") is not None
                    and not o.get("requires_pickup_point")]
            expected_min = min(fees) if fees else None
            expected_home = min(home) if home else None
            if df.get("min_fee") != expected_min:
                errors.append(
                    f"[{item_id}] delivery_fee.min_fee: options와 불일치 "
                    f"({df.get('min_fee')} != {expected_min})"
                )
            if df.get("home_delivery_fee") != expected_home:
                errors.append(
                    f"[{item_id}] delivery_fee.home_delivery_fee: options와 불일치 "
                    f"({df.get('home_delivery_fee')} != {expected_home})"
                )
            if status == "AVAILABLE" and not options:
                errors.append(f"[{item_id}] delivery_fee: status=AVAILABLE인데 options가 비어있음")
            if expected_min is not None and expected_home is None:
                warnings.append(
                    f"[{item_id}] delivery_fee: 편의점 픽업 외 배송 수단이 없음"
                    f"(home_delivery_fee=None, min_fee={expected_min})"
                )

    # location
    loc = item.get("location")
    if not isinstance(loc, dict):
        errors.append(f"[{item_id}] location: dict가 아님")
    else:
        precision = loc.get("precision")
        if precision not in VALID_LOCATION_PRECISION:
            errors.append(f"[{item_id}] location.precision: 정의되지 않은 값 '{precision}'")
        check_type(loc.get("name"), str, "location.name", item_id, errors)
        check_type(loc.get("full_address"), str, "location.full_address", item_id, errors)

        regions = loc.get("regions")
        check_type(regions, list, "location.regions", item_id, errors)
        if isinstance(regions, list):
            if precision == "NONE" and regions:
                errors.append(f"[{item_id}] location: precision=NONE인데 regions가 존재함")
            if precision != "NONE" and not regions:
                errors.append(f"[{item_id}] location: precision={precision}인데 regions가 비어있음")
            if precision == "FULL":
                missing = [r for r in regions
                           if isinstance(r, dict) and not r.get("full_address")]
                if missing:
                    errors.append(
                        f"[{item_id}] location: precision=FULL인데 full_address가 없는 지역 존재"
                    )

        # 좌표는 지오코딩 단계에서 채운다. 변환 시점에는 항상 None이어야 한다.
        if loc.get("coordinates") is not None:
            warnings.append(f"[{item_id}] location.coordinates: 변환 단계에서 채워짐")

    # brand 검사는 없다. 판매자 입력값이라 신뢰할 수 없어 통합 스키마에서 제외했다.

    # collected_at 파싱 가능 여부
    collected_at = item.get("collected_at")
    if collected_at:
        try:
            datetime.fromisoformat(str(collected_at).replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"[{item_id}] collected_at: ISO8601 형식 아님 -> {collected_at}")
    else:
        errors.append(f"[{item_id}] collected_at: 값 없음")


def summarize(items):
    by_platform = defaultdict(list)
    for it in items:
        by_platform[it.get("platform")].append(it)

    print("\n=== 플랫폼별 분포 ===")
    for platform, group in by_platform.items():
        print(f"\n[{platform}] {len(group)}건")
        print("  condition_level:", dict(Counter(i.get("condition_level") for i in group)))
        ranged = [i for i in group if isinstance(i.get("price_range"), dict)]
        if ranged:
            spreads = [
                i["price_range"]["max"] - i["price_range"]["min"] for i in ranged
            ]
            print(
                f"  옵션따라 가격변동: {len(ranged)}/{len(group)}건 "
                f"(최대 편차 {max(spreads):,}원)"
            )
        trade_flat = Counter(
            tuple(sorted(i.get("trade_method") or [])) for i in group
        )
        print("  trade_method 조합:", dict(trade_flat))
        print(
            "  delivery_fee.status:",
            dict(Counter((i.get("delivery_fee") or {}).get("status") for i in group)),
        )
        print(
            "  delivery_fee.payer:",
            dict(Counter((i.get("delivery_fee") or {}).get("payer") for i in group)),
        )
        methods = Counter(
            o.get("method")
            for i in group
            for o in ((i.get("delivery_fee") or {}).get("options") or [])
        )
        print("  배송 수단:", dict(methods))

        only_pickup = sum(
            1 for i in group
            if (i.get("delivery_fee") or {}).get("min_fee") is not None
            and (i.get("delivery_fee") or {}).get("home_delivery_fee") is None
        )
        print(f"  편의점 픽업만 가능: {only_pickup}/{len(group)}")

        print(
            "  location.precision:",
            dict(Counter((i.get("location") or {}).get("precision") for i in group)),
        )
        multi = sum(
            1 for i in group if len(((i.get("location") or {}).get("regions") or [])) > 1
        )
        print(f"  거래 지역 2곳 이상: {multi}/{len(group)}")


def validate_file(path):
    print(f"\n{'=' * 60}\n검증 대상: {path}\n{'=' * 60}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        print("⚠ items가 비어있습니다.")
        return 0, 0

    errors, warnings = [], []
    for item in items:
        validate_item(item, errors, warnings)

    print(f"\n총 {len(items)}건 검증 완료")
    print(f"오류(errors): {len(errors)}건")
    print(f"경고(warnings): {len(warnings)}건")

    if errors:
        print("\n--- 오류 목록 ---")
        for e in errors:
            print("  ✗", e)

    if warnings:
        print("\n--- 경고 목록 ---")
        for w in warnings:
            print("  ⚠", w)

    summarize(items)

    return len(errors), len(warnings)


def main():
    paths = sys.argv[1:]
    if not paths:
        print("사용법: python3 validate_unified_schema.py <unified_*.json> [...]")
        sys.exit(1)

    total_errors = 0
    total_warnings = 0
    for path in paths:
        e, w = validate_file(path)
        total_errors += e
        total_warnings += w

    print(f"\n{'=' * 60}")
    print(f"전체 결과: 오류 {total_errors}건 / 경고 {total_warnings}건")
    print("=" * 60)

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
