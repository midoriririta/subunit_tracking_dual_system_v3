from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.openalex_dashboard.cache_builder import build_aggregates, save_tables
from src.openalex_dashboard.config import CACHE_DIR, OUTPUT_DIR, get_dataset_config
from src.openalex_dashboard.matching import normalise_openalex_author_id, safe_json

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)


def _json_list(value: Any) -> list[dict[str, Any]]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
        except Exception:
            return []
    return []


def _extract_doi(*values: Any) -> str | None:
    for value in values:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        text = str(value)
        match = DOI_RE.search(text)
        if match:
            doi = match.group(0).rstrip(".,);]").strip()
            return doi.lower()
    return None


def _work_id(title: str, year: Any, doi: str | None, url: str | None) -> str:
    if doi:
        return f"doi:{doi}"
    key = "|".join([str(title or "").strip().lower(), str(year or ""), str(url or "")])
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"local:{digest}"


def _guess_source_name(citation: Any) -> str | None:
    if citation is None or (isinstance(citation, float) and pd.isna(citation)):
        return None
    text = re.sub(r"\s+", " ", str(citation)).strip()
    if not text:
        return None
    # NDPH style: "Author et al, (2025), Journal, 20"
    m = re.search(r"\(\d{4}\),\s*([^,]+)", text)
    if m:
        return m.group(1).strip(" .") or None
    # Demography style: "... ”, Nature Genetics , 57(10)"
    m = re.search(r"[\"”]\s*,\s*([^,]+?)(?:\s*,|\s+\d|\s+pp\.)", text)
    if m:
        return m.group(1).strip(" .") or None
    return None


def _person_confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low"}:
        return text
    if text in {"med", "middle"}:
        return "medium"
    return "low" if text else "low"


def _paper_confidence(person_conf: str, pub: dict[str, Any]) -> tuple[str, float, str]:
    has_title = bool(str(pub.get("title") or "").strip())
    has_doi = bool(_extract_doi(pub.get("url"), pub.get("citation")))
    has_year = bool(pub.get("year"))
    if person_conf == "high" and has_title and (has_doi or has_year):
        return "high", 0.88, "Bundled staff-profile publication; high person-level OpenAlex match; publication has DOI or year evidence."
    if person_conf in {"high", "medium"} and has_title:
        return "medium", 0.70, "Bundled staff-profile publication; person-level match is credible but paper-level OpenAlex affiliation evidence is not available in the snapshot cache."
    return "low", 0.48, "Bundled staff-profile publication with weak or missing person/paper evidence."


def build_snapshot_cache_from_staff_csv(
    input_csv: Path | str,
    dataset_key: str,
    cache_dir: Path | str = CACHE_DIR,
    output_dir: Path | str = OUTPUT_DIR,
) -> dict[str, Any]:
    """Build a lightweight bundled cache from the staff CSV only.

    This is intentionally network-free. It lets the Streamlit app open immediately
    from the committed repository. For full collaborator/institution/topic metadata,
    use the OpenAlex updater in the app or scripts/build_openalex_cache.py.
    """
    input_csv = Path(input_csv)
    cfg = get_dataset_config(dataset_key)
    roster = pd.read_csv(input_csv)
    roster = roster.copy()
    roster["staff_index"] = range(len(roster))

    people_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    works_map: dict[str, dict[str, Any]] = {}
    roster_work_rows: list[dict[str, Any]] = []
    authorships_rows: list[dict[str, Any]] = []
    institutions_rows: list[dict[str, Any]] = []

    for _, row in roster.iterrows():
        staff_index = int(row["staff_index"])
        name = row.get("name")
        author_id_short = normalise_openalex_author_id(row.get("openalex_author_id"))
        author_id_full = row.get("openalex_author_id") if pd.notna(row.get("openalex_author_id")) else None
        person_conf = _person_confidence(row.get("openalex_confidence"))
        conf_score = {"high": 0.90, "medium": 0.72, "low": 0.45}.get(person_conf, 0.45)

        people_rows.append(
            {
                **{c: row.get(c) for c in roster.columns if c != "staff_index"},
                "staff_index": staff_index,
                "openalex_author_id_short": author_id_short,
                "openalex_author_id_full": author_id_full,
                "author_display_name": name,
                "author_match_confidence": person_conf,
                "author_match_score": conf_score,
                "author_match_reasons": row.get("openalex_notes"),
            }
        )

        for rank, candidate in enumerate(_json_list(row.get("openalex_candidates_json")), start=1):
            cand_short = normalise_openalex_author_id(candidate.get("id"))
            candidate_rows.append(
                {
                    "staff_index": staff_index,
                    "staff_name": name,
                    "candidate_rank": rank,
                    "selected_for_fetch": cand_short == author_id_short,
                    "openalex_author_id_short": cand_short,
                    "openalex_author_id_full": candidate.get("id"),
                    "author_display_name": candidate.get("display_name"),
                    "author_works_count": candidate.get("works_count"),
                    "author_match_confidence": person_conf if cand_short == author_id_short else None,
                    "author_match_score": conf_score if cand_short == author_id_short else None,
                    "oxford_works": candidate.get("oxford_works"),
                }
            )

        for pub in _json_list(row.get("recent_publications_json")):
            title = str(pub.get("title") or "").strip()
            if not title:
                continue
            year = pub.get("year")
            doi = _extract_doi(pub.get("url"), pub.get("citation"))
            url = pub.get("url")
            work_id = _work_id(title, year, doi, url)
            source_name = _guess_source_name(pub.get("citation"))
            paper_conf, paper_score, paper_reasons = _paper_confidence(person_conf, pub)

            if work_id not in works_map:
                works_map[work_id] = {
                    "work_id": work_id,
                    "doi": doi,
                    "title": title,
                    "publication_year": year,
                    "publication_date": f"{int(year)}-01-01" if pd.notna(year) and str(year).isdigit() else None,
                    "work_type": pub.get("type"),
                    "cited_by_count": 0,
                    "language": None,
                    "is_oa": None,
                    "oa_status": None,
                    "oa_url": None,
                    "landing_page_url": url,
                    "pdf_url": None,
                    "source_id": None,
                    "source_name": source_name,
                    "source_type": pub.get("type"),
                    "source_is_oa": None,
                    "source_issn_l": None,
                    "volume": None,
                    "issue": None,
                    "first_page": None,
                    "last_page": None,
                    "institutions_distinct_count": 1,
                    "countries_distinct_count": 1,
                    "topics_json": safe_json([]),
                    "primary_topic_json": safe_json({}),
                    "snapshot_source": "staff_recent_publications_json",
                }

            roster_work_rows.append(
                {
                    "staff_index": staff_index,
                    "staff_name": name,
                    "openalex_author_id_short": author_id_short,
                    "openalex_author_id_full": author_id_full,
                    "author_display_name": name,
                    "author_match_score": conf_score,
                    "author_match_confidence": person_conf,
                    "work_id": work_id,
                    "title": title,
                    "publication_year": year,
                    "publication_date": works_map[work_id]["publication_date"],
                    "raw_author_name": name,
                    "author_position": None,
                    "is_corresponding": None,
                    "paper_confidence": paper_conf,
                    "paper_confidence_score": paper_score,
                    "paper_confidence_reasons": paper_reasons,
                    "paper_has_oxford_affiliation": None,
                    "paper_affiliation_score": None,
                    "paper_time_score": None,
                    "paper_name_score": None,
                }
            )

            authorships_rows.append(
                {
                    "work_id": work_id,
                    "publication_year": year,
                    "author_position": None,
                    "is_corresponding": None,
                    "author_id_short": author_id_short,
                    "author_id_full": author_id_full,
                    "author_name": name,
                    "raw_author_name": name,
                    "raw_affiliation_strings_json": safe_json(["University of Oxford"]),
                    "institution_ids_json": safe_json(["https://openalex.org/I71531966"]),
                    "institution_names_json": safe_json(["University of Oxford"]),
                    "country_codes_json": safe_json(["GB"]),
                    "institution_count": 1,
                    "country_count": 1,
                    "is_roster_person": True,
                    "roster_person_name": name,
                }
            )

    if people_rows:
        institutions_rows.append(
            {
                "institution_id": "https://openalex.org/I71531966",
                "institution_name": "University of Oxford",
                "country_code": "GB",
                "institution_type": "education",
                "ror": "https://ror.org/052gg0110",
                "from_work_id": None,
            }
        )

    tables = {
        "people": pd.DataFrame(people_rows),
        "author_candidates": pd.DataFrame(candidate_rows),
        "roster_works": pd.DataFrame(roster_work_rows),
        "works": pd.DataFrame(list(works_map.values())),
        "authorships": pd.DataFrame(authorships_rows).drop_duplicates(
            subset=["work_id", "author_id_short", "raw_author_name"], keep="first"
        ) if authorships_rows else pd.DataFrame(),
        "institutions": pd.DataFrame(institutions_rows),
        "topics_long": pd.DataFrame(
            columns=[
                "work_id",
                "publication_year",
                "topic_id",
                "topic_name",
                "topic_score",
                "is_primary_topic",
                "domain_id",
                "domain_name",
                "field_id",
                "field_name",
                "subfield_id",
                "subfield_name",
            ]
        ),
    }
    aggregates = build_aggregates(tables)
    paths = save_tables(
        tables=tables,
        aggregates=aggregates,
        output_dir=Path(cache_dir),
        output_suffix=cfg["suffix"],
        dataset_key=dataset_key,
        csv_output_dir=Path(output_dir),
    )
    return {"tables": tables, "aggregates": aggregates, "paths": paths, "dataset": cfg}
