from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.openalex_dashboard.cache_builder import build_cache_from_staff_csv
from src.openalex_dashboard.config import CACHE_DIR, OUTPUT_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or refresh the OpenAlex dashboard cache from a staff CSV.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--output_dir", default=str(CACHE_DIR))
    parser.add_argument("--dataset", choices=["demography", "ndph"], default="demography")
    parser.add_argument("--csv_output_dir", default=str(OUTPUT_DIR))
    parser.add_argument("--mailto", default=None)
    parser.add_argument("--max_candidates_per_person", type=int, default=2)
    parser.add_argument("--min_author_score", type=float, default=0.55)
    args = parser.parse_args()

    result = build_cache_from_staff_csv(
        input_csv=Path(args.input_csv),
        dataset_key=args.dataset,
        cache_dir=Path(args.output_dir),
        output_dir=Path(args.csv_output_dir),
        mailto=args.mailto,
        max_candidates_per_person=args.max_candidates_per_person,
        min_author_score=args.min_author_score,
    )
    print("Saved OpenAlex cache:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
