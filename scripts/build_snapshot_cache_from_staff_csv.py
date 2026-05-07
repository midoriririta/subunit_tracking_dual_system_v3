from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.openalex_dashboard.config import CACHE_DIR, OUTPUT_DIR
from src.openalex_dashboard.snapshot_cache import build_snapshot_cache_from_staff_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a network-free initial cache from bundled staff CSV recent_publications_json.")
    parser.add_argument("--input_csv", required=True)
    parser.add_argument("--dataset", choices=["demography", "ndph"], required=True)
    parser.add_argument("--output_dir", default=str(CACHE_DIR))
    parser.add_argument("--csv_output_dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    result = build_snapshot_cache_from_staff_csv(
        input_csv=Path(args.input_csv),
        dataset_key=args.dataset,
        cache_dir=Path(args.output_dir),
        output_dir=Path(args.csv_output_dir),
    )
    print("Saved snapshot cache:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
