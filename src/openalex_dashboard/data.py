from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd

from src.openalex_dashboard.config import (
    CACHE_DIR,
    DEFAULT_DATASET_KEY,
    OPTIONAL_CACHE_TABLES,
    REQUIRED_AGGREGATES,
    REQUIRED_CACHE_TABLES,
    get_dataset_config,
)

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    class _DummyStreamlit:
        @staticmethod
        def cache_data(*args, **kwargs):
            def decorator(func):
                return func
            return decorator
    st = _DummyStreamlit()


def first_existing(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def safe_json_loads(value: Any):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def explode_json_list_column(df: pd.DataFrame, column: str, out_column: str) -> pd.DataFrame:
    if column not in df.columns or df.empty:
        return pd.DataFrame(columns=list(df.columns) + [out_column])
    tmp = df.copy()
    tmp[out_column] = tmp[column].apply(safe_json_loads)
    tmp = tmp.explode(out_column)
    tmp = tmp[tmp[out_column].notna()]
    tmp = tmp[tmp[out_column] != ""]
    return tmp


def _path_with_suffix(directory: Path, stem: str, suffix: str) -> Path:
    return directory / f"{stem}{suffix}.parquet"


def resolve_cache_paths(dataset_key: str = DEFAULT_DATASET_KEY, cache_dir: Path | str = CACHE_DIR) -> Dict[str, Any]:
    cache_dir = Path(cache_dir)
    dataset = get_dataset_config(dataset_key)
    suffix = dataset["suffix"]
    aggregates_dir = cache_dir / "aggregates"
    required = {table_name: _path_with_suffix(cache_dir, table_name, suffix) for table_name in REQUIRED_CACHE_TABLES}
    optional = {table_name: _path_with_suffix(cache_dir, table_name, suffix) for table_name in OPTIONAL_CACHE_TABLES}
    aggregate_paths = {agg_name: _path_with_suffix(aggregates_dir, agg_name, suffix) for agg_name in REQUIRED_AGGREGATES}
    return {
        "dataset": dataset,
        "cache_dir": cache_dir,
        "required": required,
        "optional": optional,
        "aggregate_paths": aggregate_paths,
    }


def cache_status(dataset_key: str = DEFAULT_DATASET_KEY, cache_dir: Path | str = CACHE_DIR) -> Dict[str, Any]:
    paths = resolve_cache_paths(dataset_key, cache_dir)
    required = paths["required"]
    missing = [name for name, path in required.items() if not path.exists()]
    return {**paths, "missing": missing, "complete": len(missing) == 0}


def _fallback_roster_works(bundle: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    works = bundle.get("works", pd.DataFrame())
    authorships = bundle.get("authorships", pd.DataFrame())
    if works.empty or authorships.empty or "is_roster_person" not in authorships.columns:
        return pd.DataFrame()
    roster_auth = authorships[authorships["is_roster_person"].fillna(False)].copy()
    keep_cols = [c for c in ["work_id", "publication_year", "roster_person_name", "author_id_short", "author_id_full", "author_name", "raw_author_name"] if c in roster_auth.columns]
    out = roster_auth[keep_cols].drop_duplicates().rename(columns={"roster_person_name": "staff_name"})
    out["paper_confidence"] = "high"
    out["paper_confidence_score"] = 1.0
    out["paper_confidence_reasons"] = "Legacy cache without paper-level confidence; treated as high for backward compatibility."
    if "title" in works.columns:
        out = out.merge(works[["work_id", "title"]].drop_duplicates(), on="work_id", how="left")
    return out


@st.cache_data(show_spinner=True)
def load_bundle(dataset_key: str = DEFAULT_DATASET_KEY, cache_dir: Path | str = CACHE_DIR) -> Dict[str, Any]:
    status = cache_status(dataset_key=dataset_key, cache_dir=cache_dir)
    dataset = status["dataset"]
    required = status["required"]
    optional = status["optional"]
    aggregate_paths = status["aggregate_paths"]
    cache_dir = status["cache_dir"]
    missing = status["missing"]
    if missing:
        raise FileNotFoundError(
            f"Missing required cache files for {dataset['label']} in {cache_dir}: {missing} "
            f"(expected suffix '{dataset['suffix']}')."
        )

    bundle = {name: pd.read_parquet(path) for name, path in required.items()}
    for name, path in optional.items():
        if path.exists():
            bundle[name] = pd.read_parquet(path)
        else:
            bundle[name] = pd.DataFrame()

    if bundle["roster_works"].empty:
        bundle["roster_works"] = _fallback_roster_works(bundle)

    bundle["aggregates"] = {}
    for agg_name, agg_path in aggregate_paths.items():
        if agg_path.exists():
            try:
                bundle["aggregates"][agg_name] = pd.read_parquet(agg_path)
            except Exception:
                pass

    for table_name in ["works", "authorships", "topics_long", "roster_works"]:
        if table_name in bundle and "publication_year" in bundle[table_name].columns:
            bundle[table_name]["publication_year"] = pd.to_numeric(
                bundle[table_name]["publication_year"], errors="coerce"
            ).astype("Int64")
    if "publication_date" in bundle["works"].columns:
        bundle["works"]["publication_date"] = pd.to_datetime(bundle["works"]["publication_date"], errors="coerce")
    if "publication_date" in bundle["roster_works"].columns:
        bundle["roster_works"]["publication_date"] = pd.to_datetime(
            bundle["roster_works"]["publication_date"], errors="coerce"
        )

    people = bundle["people"]
    bundle["person_name_col"] = first_existing(
        people, ["name", "person_name", "full_name", "display_name", "author_display_name"]
    )
    confidence_col = None
    for col in people.columns:
        if "confidence" in col.lower():
            confidence_col = col
            break
    bundle["confidence_col"] = confidence_col
    bundle["dataset"] = dataset
    bundle["dataset_key"] = dataset["key"]
    bundle["cache_paths"] = status
    return bundle


def clear_streamlit_cache() -> None:
    try:
        load_bundle.clear()
    except Exception:
        pass
