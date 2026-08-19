from playwright.sync_api import sync_playwright
import json
import re
from datetime import datetime

def clean(text):
    """공백 및 각주 기호 정리"""
    return re.sub(r'\s*각주\s*[\^¹²³⁴⁵⁶⁷⁸⁹⁰]+', '', text).strip()

def crawl_airpods_pro3():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.set_extra_http_headers({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9"
        })

        url = "https://www.apple.com/kr/shop/buy-airpods/airpods-pro-3"
        print(f"🔍 페이지 로딩 중... {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)

        data = {}

        # ── 1. 기본 정보 ──────────────────────────────────────
        data["url"] = url
        data["crawled_at"] = datetime.now().isoformat()

        # 제품명
        title_el = page.query_selector("h1")
        data["product_name"] = clean(title_el.inner_text()) if title_el else None

        # 가격
        price_el = page.query_selector("a[href*='step=select']")
        data["price"] = clean(price_el.inner_text()) if price_el else None

        # 설명 문구
        desc_el = page.query_selector("h1 + p, h1 ~ p")
        data["description"] = clean(desc_el.inner_text()) if desc_el else None

        # ── 2. 제품 개요 (긴 설명) ────────────────────────────
        overview_els = page.query_selector_all("section li p, .rf-bfe-overview p")
        overview_texts = [clean(el.inner_text()) for el in overview_els if el.inner_text().strip()]
        data["overview"] = overview_texts[:5] if overview_texts else []

        # ── 3. 제품 구성 ──────────────────────────────────────
        box_items = page.query_selector_all("ul li")
        box_texts = []
        for el in box_items:
            t = clean(el.inner_text())
            # 제품 구성 키워드 포함된 항목만
            if any(kw in t for kw in ["AirPods", "케이스", "이어팁", "설명서", "USB"]):
                box_texts.append(t)
        data["in_the_box"] = list(dict.fromkeys(box_texts))  # 중복 제거

        # ── 4. 주요 기능 (비교표에서 추출) ────────────────────
        features = []
        feature_els = page.query_selector_all("ul li")
        keywords = ["노이즈", "심박수", "배터리", "번역", "공간 음향", "방수", "MagSafe", "Siri", "IP5"]
        for el in feature_els:
            t = clean(el.inner_text())
            if any(kw in t for kw in keywords) and len(t) > 5:
                features.append(t)
        data["key_features"] = list(dict.fromkeys(features))[:15]

        # ── 5. 배터리 ─────────────────────────────────────────
        battery_match = re.search(r'ANC.*?최대\s*(\d+)시간', " ".join(data["key_features"]))
        data["battery_anc_hours"] = int(battery_match.group(1)) if battery_match else None

        # ── 6. 방수 등급 ──────────────────────────────────────
        ip_match = re.search(r'IP\d+', " ".join(data["key_features"]))
        data["water_resistance"] = ip_match.group(0) if ip_match else None

        # ── 7. 자주 묻는 질문 ─────────────────────────────────
        faq = []
        faq_q_els = page.query_selector_all("details summary, .faq-question, [aria-expanded]")
        for el in faq_q_els:
            q = clean(el.inner_text())
            if q and len(q) > 5:
                faq.append({"question": q})
        # 대안: h3 태그에서 FAQ 추출
        if not faq:
            h3_els = page.query_selector_all("h3")
            for el in h3_els:
                t = clean(el.inner_text())
                if "?" in t or "인지" in t or "어디" in t:
                    faq.append({"question": t})
        data["faq"] = faq[:5]

        # ── 8. 비교 모델 ──────────────────────────────────────
        compare_models = []
        compare_h3_els = page.query_selector_all("h3 a, .rf-bfe-column h3")
        for el in compare_h3_els:
            t = clean(el.inner_text())
            if "AirPods" in t or "AirPods Max" in t:
                href = el.get_attribute("href") or ""
                compare_models.append({"name": t, "url": href})
        data["compare_models"] = list({m["name"]: m for m in compare_models}.values())

        browser.close()

        # ── JSON 저장 ──────────────────────────────────────────
        output_file = "airpods_pro3.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 크롤링 완료! → {output_file}")
        print(f"  제품명: {data['product_name']}")
        print(f"  가격:   {data['price']}")
        print(f"  방수:   {data['water_resistance']}")
        print(f"  배터리: {data['battery_anc_hours']}시간 (ANC)")
        print(f"  주요기능 {len(data['key_features'])}개, 제품구성 {len(data['in_the_box'])}개 수집")

        return data

if __name__ == "__main__":
    crawl_airpods_pro3()