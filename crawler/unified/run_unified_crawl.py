"""세 플랫폼을 한 번에 크롤링하고 통합 스키마로 변환한다.

번개장터 / 중고나라 / N플리마켓 크롤러를 차례로 실행한 뒤
transform_to_unified_schema.py로 합치고, 필요하면 검증까지 이어서 돌린다.

예시:
    python3 run_unified_crawl.py "닌텐도 스위치 OLED"
    python3 run_unified_crawl.py "냉장고" --limit 10 --validate
    python3 run_unified_crawl.py "샤넬 가방" --outdir ../../output --keep-raw

한 플랫폼이 0건이거나 실패해도 나머지 결과로 변환을 진행한다.
플랫폼마다 검색 결과가 없는 상품군이 실제로 존재하기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

UNIFIED_DIR = Path(__file__).resolve().parent
CRAWLER_DIR = UNIFIED_DIR.parent

# (플랫폼 키, 크롤러 스크립트 경로)
CRAWLERS = (
    ("bunjang", CRAWLER_DIR / "bunjang-crawler" / "bunjang_crawler.py"),
    ("joongna", CRAWLER_DIR / "joongna-crawler" / "joongna_crawler.py"),
    ("naver_fleamarket",
     CRAWLER_DIR / "naver-fleamarket-crawler" / "naver_fleamarket_crawler.py"),
    # 새상품 비교 기준. 중고만 모으면 "새것을 살 필요가 있는가"를 판단할 수 없다.
    ("elevenst", CRAWLER_DIR / "11st-crawler" / "elevenst_crawler.py"),
)

# 11번가는 다른 크롤러와 다르게 다룬다.
#
# 정렬 — 중고는 최신 매물이 중요하지만(먼저 올라온 게 먼저 팔린다) 새상품은
# 그렇지 않다. 같은 물건이 여러 판매자에게 올라와 있어 인기순 상위가 기준가에
# 가깝다. 11번가 최신순은 방금 등록된 액세서리를 위로 올린다.
#
# 개수 — 새상품은 기준가 확인용이라 중고보다 적게 모은다. 같은 물건이 여러
# 판매자에게 비슷한 값으로 올라와 있어 상위 몇 건이면 기준가를 잡을 수 있다.
# 반대로 중고는 매물마다 상태와 가격이 제각각이라 넓게 봐야 한다.
ELEVENST_SORT = "popular"

DEFAULT_SORT = "latest"
DEFAULT_LIMIT = 3

# 11번가는 중고 플랫폼당 개수의 절반만, 그리고 최대 4건까지만 모은다.
#
# 새상품은 파는 곳이 한정돼 있다. 같은 물건이 여러 판매자에게 비슷한 값으로
# 올라와 있어 상위 몇 건이면 기준가가 잡힌다. 더 모아 봐야 같은 상품이 반복되고,
# 인기순 아래로 내려갈수록 액세서리가 섞일 여지만 는다.
#
# 최소 2건은 있어야 기준가가 한 판매자에게 휘둘리지 않는다.
ELEVENST_LIMIT_DIVISOR = 2
ELEVENST_MIN_LIMIT = 2
ELEVENST_MAX_LIMIT = 4


def elevenst_limit(limit: int) -> int:
    return min(ELEVENST_MAX_LIMIT, max(ELEVENST_MIN_LIMIT, limit // ELEVENST_LIMIT_DIVISOR))

TRANSFORM = UNIFIED_DIR / "transform_to_unified_schema.py"
VALIDATE = UNIFIED_DIR / "validate_unified_schema.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="세 플랫폼을 한 번에 크롤링하고 통합 스키마로 변환합니다."
    )
    parser.add_argument("query", help='검색할 상품명. 예: "닌텐도 스위치 OLED"')
    parser.add_argument(
        # 기본값을 None 으로 두어 "사용자가 직접 지정했는지"를 구분한다.
        # 지정하지 않으면 11번가만 다른 값을 쓴다.
        "--sort", choices=("latest", "score"), default=None,
        help="latest=최신순, score=정확도순 (기본값: 중고는 latest, 11번가는 popular)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help=f"중고 플랫폼당 수집할 상품 수 (기본값 {DEFAULT_LIMIT}). "
             "11번가는 새상품 기준가 확인용이라 이 값의 절반만, 최대 4건까지 모은다",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="요청 사이 대기 시간(초) (기본값: 1.0)",
    )
    parser.add_argument(
        "--outdir", type=Path, default=UNIFIED_DIR / "output",
        help="결과를 저장할 폴더 (기본값: unified/output)",
    )
    parser.add_argument(
        "--keep-raw", action="store_true",
        help="플랫폼별 원본 JSON도 남긴다. 생략하면 통합 결과만 남는다",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="변환 후 검증 스크립트까지 실행한다",
    )
    return parser.parse_args()


def safe_name(query: str) -> str:
    """검색어를 파일명으로 쓸 수 있게 정리한다."""
    name = re.sub(r"[^0-9a-zA-Z가-힣_-]+", "_", query).strip("_")
    return name[:60] or "products"


def run_crawler(script: Path, query: str, args: argparse.Namespace,
                output: Path, key: str) -> bool:
    """크롤러 하나를 실행한다. 성공 여부를 반환한다.

    11번가만 정렬과 개수를 따로 준다. 사용자가 --sort / --limit 를 직접
    지정하면 그 값을 그대로 쓴다.
    """
    is_elevenst = key == "elevenst"
    base_limit = args.limit or DEFAULT_LIMIT
    sort = args.sort or (ELEVENST_SORT if is_elevenst else DEFAULT_SORT)
    limit = elevenst_limit(base_limit) if is_elevenst else base_limit

    command = [
        sys.executable, str(script), query,
        "--sort", sort,
        "--limit", str(limit),
        "--delay", str(args.delay),
        "--output", str(output),
    ]
    print(f"\n[{script.stem}] 실행", flush=True)
    result = subprocess.run(command, cwd=script.parent)
    if result.returncode != 0:
        print(f"[{script.stem}] 실패(코드 {result.returncode}) — 빈 결과로 계속 진행",
              file=sys.stderr)
        return False
    return True


def write_empty(path: Path, query: str, args: argparse.Namespace) -> None:
    """크롤러가 실패했을 때 변환이 멈추지 않도록 빈 결과를 만든다."""
    path.write_text(
        json.dumps(
            {"query": query,
             "sort": args.sort or DEFAULT_SORT,
             "requestedCount": args.limit or DEFAULT_LIMIT,
             "count": 0, "failedCount": 0, "products": [], "errors": []},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )


def count_products(path: Path) -> int:
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("products", []))
    except (OSError, json.JSONDecodeError):
        return 0


def main() -> None:
    args = parse_args()
    query = args.query.strip()
    if not query:
        print("[오류] 검색어를 입력해야 합니다.", file=sys.stderr)
        sys.exit(1)

    args.outdir.mkdir(parents=True, exist_ok=True)
    name = safe_name(query)

    # --keep-raw가 없으면 원본은 임시 폴더에 두고 끝나면 지운다.
    with tempfile.TemporaryDirectory() as tmp:
        raw_dir = args.outdir if args.keep_raw else Path(tmp)

        raw_paths = {}
        for key, script in CRAWLERS:
            path = raw_dir / f"{key}_{name}.json"
            if not run_crawler(script, query, args, path, key) or not path.exists():
                write_empty(path, query, args)
            raw_paths[key] = path

        print("\n[수집 결과]", flush=True)
        for key, path in raw_paths.items():
            print(f"  {key:18} {count_products(path)}건", flush=True)

        unified_path = args.outdir / f"unified_{name}.json"
        transform_command = [
            sys.executable, str(TRANSFORM),
            "--bunjang", str(raw_paths["bunjang"]),
            "--joongna", str(raw_paths["joongna"]),
            "--naver-fleamarket", str(raw_paths["naver_fleamarket"]),
            "--elevenst", str(raw_paths["elevenst"]),
            "--output", str(unified_path),
        ]
        print("\n[변환]", flush=True)
        if subprocess.run(transform_command).returncode != 0:
            print("[오류] 변환 실패", file=sys.stderr)
            sys.exit(1)

    if args.validate:
        print("\n[검증]", flush=True)
        code = subprocess.run(
            [sys.executable, str(VALIDATE), str(unified_path)]
        ).returncode
        sys.exit(code)


if __name__ == "__main__":
    main()
