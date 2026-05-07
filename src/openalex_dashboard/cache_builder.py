from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable
import json

import pandas as pd

from src.openalex_dashboard.config import CACHE_DIR, OUTPUT_DIR, get_dataset_config
from src.openalex_dashboard.matching import (
    AuthorMatch,
    extract_staff_fields,
    normalise_openalex_author_id,
    safe_json,
    score_author_candidate,
    score_work_for_staff,
)
from src.openalex_dashboard.openalex_client import OpenAlexClient

ProgressFn = Callable[[str], None]


def _log(progress: ProgressFn | None, message: str) -> None:
    print(message)
    if progress:
        progress(message)


def _path_with_suffix(directory: Path, stem: str, suffix: str) -> Path:
    return directory / f"{stem}{suffix}.parquet"


def _csv_path(dataset_key: str, output_dir: Path) -> Path:
    return output_dir / f"scraped_publications_{dataset_key}.csv"


def read_staff_csv(input_csv: Path | str) -> pd.DataFrame:
    df = pd.read_csv(input_csv)
    lowered = {str(c).lower().strip(): c for c in df.columns}
    if not any(c in lowered for c in ["name", "full_name", "person_name", "staff_name", "display_name"]):
        raise ValueError(
            "Staff CSV must include one name column: name, full_name, person_name, staff_name, or display_name."
        )
    out = df.copy()
    out["staff_index"] = range(len(out))
    extracted = out.apply(extract_staff_fields, axis=1, result_type="expand")
    for col in extracted.columns:
        out[f"staff_{col}"] = extracted[col]
    out["staff_openalex_author_id_short"] = out["staff_openalex_author_id"].map(normalise_openalex_author_id)
    return out


def choose_author_matches(
    staff_df: pd.DataFrame,
    client: OpenAlexClient,
    max_candidates_per_person: int = 2,
    min_author_score: float = 0.55,
    progress: ProgressFn | None = None,
) -> tuple[pd.DataFrame, list[AuthorMatch]]:
    candidate_rows: list[dict[str, Any]] = []
    chosen: list[AuthorMatch] = []

    for _, row in staff_df.iterrows():
        staff = extract_staff_fields(row)
        staff_index = int(row["staff_index"])
        staff_name = str(staff.get("name") or "").strip()
        explicit_author_id = normalise_openalex_author_id(staff.get("openalex_author_id"))

        records: list[tuple[dict[str, Any], bool]] = []
        if explicit_author_id:
            try:
                records.append((client.fetch_author(explicit_author_id), True))
            except Exception as exc:
                _log(progress, f"[WARN] Could not fetch explicit author ID {explicit_author_id} for {staff_name}: {exc}")

        if not records and staff_name:
            try:
                for rec in client.search_authors(staff_name, per_page=10):
                    records.append((rec, False))
            except Exception as exc:
                _log(progress, f"[WARN] Could not search OpenAlex authors for {staff_name}: {exc}")

        scored: list[tuple[float, str, list[str], dict[str, Any], bool]] = []
        seen_ids: set[str] = set()
        for rec, explicit in records:
            aid_short = normalise_openalex_author_id(rec.get("id"))
            if not aid_short or aid_short in seen_ids:
                continue
            seen_ids.add(aid_short)
            score, confidence, reasons = score_author_candidate(staff, rec, explicit_id=explicit)
            scored.append((score, confidence, reasons, rec, explicit))

        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] < min_author_score:
            # Keep the best candidate as low confidence so the user can inspect it,
            # but it will not enter the default high-confidence webapp view.
            keep_scored = scored[:1]
        else:
            keep_scored = [x for x in scored if x[0] >= min_author_score][:max_candidates_per_person]

        for rank, (score, confidence, reasons, rec, explicit) in enumerate(scored, start=1):
            aid_short = normalise_openalex_author_id(rec.get("id")) or ""
            ids = rec.get("ids") or {}
            candidate_rows.append(
                {
                    "staff_index": staff_index,
                    "staff_name": staff_name,
                    "candidate_rank": rank,
                    "selected_for_fetch": any(normalise_openalex_author_id(k[3].get("id")) == aid_short for k in keep_scored),
                    "openalex_author_id_short": aid_short,
                    "openalex_author_id_full": rec.get("id"),
                    "author_display_name": rec.get("display_name"),
                    "author_orcid": ids.get("orcid"),
                    "author_works_count": rec.get("works_count"),
                    "author_cited_by_count": rec.get("cited_by_count"),
                    "author_match_score": round(score, 4),
                    "author_match_confidence": confidence,
                    "author_match_reasons": "; ".join(reasons),
                    "explicit_openalex_id": explicit,
                    "author_last_known_institutions_json": safe_json(rec.get("last_known_institutions")),
                }
            )

        for score, confidence, reasons, rec, _explicit in keep_scored:
            aid_short = normalise_openalex_author_id(rec.get("id")) or ""
            chosen.append(
                AuthorMatch(
                    staff_index=staff_index,
                    staff_name=staff_name,
                    openalex_author_id_short=aid_short,
                    openalex_author_id_full=rec.get("id") or f"https://openalex.org/{aid_short}",
                    author_display_name=rec.get("display_name") or "",
                    score=score,
                    confidence=confidence,
                    reasons=reasons,
                    record=rec,
                )
            )
        _log(progress, f"Matched author candidates for {staff_name or staff_index}: kept {len(keep_scored)} candidate(s).")

    return pd.DataFrame(candidate_rows), chosen


def extract_source_fields(primary_location: dict[str, Any] | None) -> dict[str, Any]:
    pl = primary_location or {}
    source = pl.get("source") or {}
    return {
        "source_id": source.get("id"),
        "source_name": source.get("display_name"),
        "source_type": source.get("type"),
        "source_is_oa": source.get("is_oa"),
        "source_issn_l": source.get("issn_l"),
    }


def find_authorship_for_author(work: dict[str, Any], author_id_short: str) -> dict[str, Any] | None:
    for auth in work.get("authorships") or []:
        author = auth.get("author") or {}
        if normalise_openalex_author_id(author.get("id")) == author_id_short:
            return auth
    return None


def build_tables(
    staff_df: pd.DataFrame,
    chosen_matches: list[AuthorMatch],
    client: OpenAlexClient,
    progress: ProgressFn | None = None,
) -> dict[str, pd.DataFrame]:
    staff_by_index = {int(row["staff_index"]): extract_staff_fields(row) for _, row in staff_df.iterrows()}
    staff_name_by_author: dict[str, list[str]] = {}
    for match in chosen_matches:
        staff_name_by_author.setdefault(match.openalex_author_id_short, []).append(match.staff_name)

    works_map: dict[str, dict[str, Any]] = {}
    roster_work_rows: list[dict[str, Any]] = []
    authorships_rows: list[dict[str, Any]] = []
    institutions_rows: list[dict[str, Any]] = []
    topics_rows: list[dict[str, Any]] = []
    seen_authorship_keys: set[tuple[Any, ...]] = set()

    for i, match in enumerate(chosen_matches, start=1):
        _log(progress, f"Fetching works for {match.staff_name} ({match.openalex_author_id_short}) [{i}/{len(chosen_matches)}] ...")
        raw_works = list(client.iter_works_for_author(match.openalex_author_id_short))
        _log(progress, f"  fetched {len(raw_works):,} works for {match.staff_name}")
        staff = staff_by_index.get(match.staff_index, {"name": match.staff_name})

        for work in raw_works:
            work_id = work.get("id")
            if not work_id:
                continue

            authorship = find_authorship_for_author(work, match.openalex_author_id_short)
            if not authorship:
                continue

            if work_id not in works_map:
                primary_location = work.get("primary_location") or {}
                source_fields = extract_source_fields(primary_location)
                open_access = work.get("open_access") or {}
                best_oa = work.get("best_oa_location") or {}
                ids = work.get("ids") or {}
                biblio = work.get("biblio") or {}
                all_country_codes = set()
                all_institution_ids = set()
                for auth in work.get("authorships") or []:
                    for inst in auth.get("institutions") or []:
                        iid = inst.get("id")
                        ccode = inst.get("country_code")
                        if iid:
                            all_institution_ids.add(iid)
                        if ccode:
                            all_country_codes.add(ccode)

                works_map[work_id] = {
                    "work_id": work_id,
                    "doi": work.get("doi") or ids.get("doi"),
                    "title": work.get("display_name"),
                    "publication_year": work.get("publication_year"),
                    "publication_date": work.get("publication_date"),
                    "work_type": work.get("type"),
                    "cited_by_count": work.get("cited_by_count"),
                    "language": work.get("language"),
                    "is_oa": open_access.get("is_oa"),
                    "oa_status": open_access.get("oa_status"),
                    "oa_url": open_access.get("oa_url"),
                    "landing_page_url": best_oa.get("landing_page_url") or ids.get("doi") or work.get("id"),
                    "pdf_url": best_oa.get("pdf_url"),
                    "source_id": source_fields["source_id"],
                    "source_name": source_fields["source_name"],
                    "source_type": source_fields["source_type"],
                    "source_is_oa": source_fields["source_is_oa"],
                    "source_issn_l": source_fields["source_issn_l"],
                    "volume": biblio.get("volume"),
                    "issue": biblio.get("issue"),
                    "first_page": biblio.get("first_page"),
                    "last_page": biblio.get("last_page"),
                    "institutions_distinct_count": len(all_institution_ids),
                    "countries_distinct_count": len(all_country_codes),
                    "topics_json": safe_json(work.get("topics")),
                    "primary_topic_json": safe_json(work.get("primary_topic")),
                }

                for auth in work.get("authorships") or []:
                    author = auth.get("author") or {}
                    aid_short = normalise_openalex_author_id(author.get("id"))
                    institutions = auth.get("institutions") or []
                    inst_ids = [x.get("id") for x in institutions if x.get("id")]
                    inst_names = [x.get("display_name") for x in institutions if x.get("display_name")]
                    country_codes = sorted({x.get("country_code") for x in institutions if x.get("country_code")})
                    key = (work_id, aid_short, auth.get("raw_author_name"), auth.get("author_position"))
                    if key not in seen_authorship_keys:
                        seen_authorship_keys.add(key)
                        authorships_rows.append(
                            {
                                "work_id": work_id,
                                "publication_year": work.get("publication_year"),
                                "author_position": auth.get("author_position"),
                                "is_corresponding": auth.get("is_corresponding"),
                                "author_id_short": aid_short,
                                "author_id_full": author.get("id"),
                                "author_name": author.get("display_name"),
                                "raw_author_name": auth.get("raw_author_name"),
                                "raw_affiliation_strings_json": safe_json(auth.get("raw_affiliation_strings")),
                                "institution_ids_json": safe_json(inst_ids),
                                "institution_names_json": safe_json(inst_names),
                                "country_codes_json": safe_json(country_codes),
                                "institution_count": len(inst_ids),
                                "country_count": len(country_codes),
                                "is_roster_person": aid_short in staff_name_by_author,
                                "roster_person_name": "; ".join(staff_name_by_author.get(aid_short, [])),
                            }
                        )
                    for inst in institutions:
                        if inst.get("id"):
                            institutions_rows.append(
                                {
                                    "institution_id": inst.get("id"),
                                    "institution_name": inst.get("display_name"),
                                    "country_code": inst.get("country_code"),
                                    "institution_type": inst.get("type"),
                                    "ror": inst.get("ror"),
                                    "from_work_id": work_id,
                                }
                            )

                primary_topic_id = (work.get("primary_topic") or {}).get("id")
                for topic in work.get("topics") or []:
                    domain = topic.get("domain") or {}
                    field = topic.get("field") or {}
                    subfield = topic.get("subfield") or {}
                    topics_rows.append(
                        {
                            "work_id": work_id,
                            "publication_year": work.get("publication_year"),
                            "topic_id": topic.get("id"),
                            "topic_name": topic.get("display_name"),
                            "topic_score": topic.get("score"),
                            "is_primary_topic": topic.get("id") == primary_topic_id,
                            "domain_id": domain.get("id"),
                            "domain_name": domain.get("display_name"),
                            "field_id": field.get("id"),
                            "field_name": field.get("display_name"),
                            "subfield_id": subfield.get("id"),
                            "subfield_name": subfield.get("display_name"),
                        }
                    )

            paper_score = score_work_for_staff(
                staff=staff,
                author_match_score=match.score,
                author_match_confidence=match.confidence,
                work=work,
                authorship=authorship,
            )
            author = authorship.get("author") or {}
            roster_work_rows.append(
                {
                    "staff_index": match.staff_index,
                    "staff_name": match.staff_name,
                    "openalex_author_id_short": match.openalex_author_id_short,
                    "openalex_author_id_full": match.openalex_author_id_full,
                    "author_display_name": match.author_display_name,
                    "author_match_score": round(match.score, 4),
                    "author_match_confidence": match.confidence,
                    "work_id": work_id,
                    "title": work.get("display_name"),
                    "publication_year": work.get("publication_year"),
                    "publication_date": work.get("publication_date"),
                    "raw_author_name": authorship.get("raw_author_name") or author.get("display_name"),
                    "author_position": authorship.get("author_position"),
                    "is_corresponding": authorship.get("is_corresponding"),
                    **paper_score,
                }
            )

    people_rows = []
    candidates_by_staff = {}
    for match in chosen_matches:
        candidates_by_staff.setdefault(match.staff_index, []).append(match)

    for _, row in staff_df.iterrows():
        staff_index = int(row["staff_index"])
        matches = candidates_by_staff.get(staff_index, [])
        best = max(matches, key=lambda m: m.score) if matches else None
        people_rows.append(
            {
                "staff_index": staff_index,
                "name": row.get("staff_name") or row.get("name") or row.get("full_name"),
                "email": row.get("staff_email"),
                "orcid": row.get("staff_orcid"),
                "primary_institution": row.get("staff_primary_institution"),
                "department": row.get("staff_department"),
                "subunit": row.get("staff_subunit"),
                "start_year": row.get("staff_start_year"),
                "end_year": row.get("staff_end_year"),
                "openalex_author_id_short": best.openalex_author_id_short if best else None,
                "openalex_author_id_full": best.openalex_author_id_full if best else None,
                "author_display_name": best.author_display_name if best else None,
                "author_match_score": round(best.score, 4) if best else None,
                "author_match_confidence": best.confidence if best else None,
                "author_match_reasons": "; ".join(best.reasons) if best else None,
                "candidate_count_fetched": len(matches),
            }
        )

    for match in chosen_matches:
        for inst in match.record.get("last_known_institutions") or []:
            if inst.get("id"):
                institutions_rows.append(
                    {
                        "institution_id": inst.get("id"),
                        "institution_name": inst.get("display_name"),
                        "country_code": inst.get("country_code"),
                        "institution_type": inst.get("type"),
                        "ror": inst.get("ror"),
                        "from_work_id": None,
                    }
                )

    tables = {
        "people": pd.DataFrame(people_rows),
        "roster_works": pd.DataFrame(roster_work_rows),
        "works": pd.DataFrame(list(works_map.values())),
        "authorships": pd.DataFrame(authorships_rows),
        "institutions": pd.DataFrame(institutions_rows),
        "topics_long": pd.DataFrame(topics_rows),
    }
    if not tables["institutions"].empty:
        tables["institutions"] = tables["institutions"].drop_duplicates(subset=["institution_id"])
    if not tables["topics_long"].empty:
        tables["topics_long"] = tables["topics_long"].drop_duplicates(subset=["work_id", "topic_id"])
    if not tables["roster_works"].empty:
        tables["roster_works"] = tables["roster_works"].drop_duplicates(
            subset=["staff_index", "openalex_author_id_short", "work_id"]
        )
    if not tables["works"].empty:
        tables["works"] = tables["works"].drop_duplicates(subset=["work_id"])
    return tables


def build_aggregates(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    works_df = tables.get("works", pd.DataFrame()).copy()
    roster_works = tables.get("roster_works", pd.DataFrame()).copy()
    authorships_df = tables.get("authorships", pd.DataFrame()).copy()
    topics_long_df = tables.get("topics_long", pd.DataFrame()).copy()

    if works_df.empty:
        return {
            "agg_publications_by_year": pd.DataFrame(),
            "agg_citations_by_pubyear": pd.DataFrame(),
            "agg_collaborator_countries_by_year": pd.DataFrame(),
            "agg_domains_by_year": pd.DataFrame(),
            "agg_sources_by_year": pd.DataFrame(),
            "agg_confidence_by_year": pd.DataFrame(),
        }

    agg: dict[str, pd.DataFrame] = {}
    agg["agg_publications_by_year"] = (
        works_df.dropna(subset=["publication_year"])
        .groupby("publication_year", as_index=False)
        .agg(
            works_count=("work_id", "nunique"),
            total_citations=("cited_by_count", "sum"),
            mean_citations=("cited_by_count", "mean"),
            oa_works_count=("is_oa", lambda s: int(pd.Series(s).fillna(False).sum())),
        )
        .sort_values("publication_year")
    )
    agg["agg_citations_by_pubyear"] = (
        works_df.dropna(subset=["publication_year"])
        .groupby("publication_year", as_index=False)
        .agg(
            works_count=("work_id", "nunique"),
            total_citations=("cited_by_count", "sum"),
            mean_citations=("cited_by_count", "mean"),
            median_citations=("cited_by_count", "median"),
            max_citations=("cited_by_count", "max"),
        )
        .sort_values("publication_year")
    )
    if not authorships_df.empty and "country_codes_json" in authorships_df.columns:
        countries = authorships_df.copy()
        countries["country_codes_json"] = countries["country_codes_json"].fillna("[]")
        countries["country_code"] = countries["country_codes_json"].apply(
            lambda x: json.loads(x) if isinstance(x, str) and x.startswith("[") else []
        )
        countries = countries.explode("country_code")
        countries = countries[
            (~countries["is_roster_person"].fillna(False))
            & (countries["country_code"].notna())
            & (countries["country_code"] != "")
        ]
        agg["agg_collaborator_countries_by_year"] = (
            countries.groupby(["publication_year", "country_code"], as_index=False)
            .agg(
                external_authorship_rows=("work_id", "size"),
                collaborator_works_count=("work_id", "nunique"),
                unique_external_authors=("author_id_short", "nunique"),
            )
            .sort_values(["publication_year", "collaborator_works_count"], ascending=[True, False])
        )
    else:
        agg["agg_collaborator_countries_by_year"] = pd.DataFrame()

    if not topics_long_df.empty and "domain_name" in topics_long_df.columns:
        agg["agg_domains_by_year"] = (
            topics_long_df.dropna(subset=["publication_year", "domain_name"])
            .groupby(["publication_year", "domain_id", "domain_name"], as_index=False)
            .agg(works_count=("work_id", "nunique"))
            .sort_values(["publication_year", "works_count"], ascending=[True, False])
        )
    else:
        agg["agg_domains_by_year"] = pd.DataFrame()

    if "source_id" in works_df.columns:
        agg["agg_sources_by_year"] = (
            works_df.dropna(subset=["publication_year"])
            .groupby(["publication_year", "source_id", "source_name", "source_type"], as_index=False, dropna=False)
            .agg(works_count=("work_id", "nunique"), total_citations=("cited_by_count", "sum"))
            .sort_values(["publication_year", "works_count"], ascending=[True, False])
        )
    else:
        agg["agg_sources_by_year"] = pd.DataFrame()

    if not roster_works.empty:
        agg["agg_confidence_by_year"] = (
            roster_works.dropna(subset=["publication_year"])
            .groupby(["publication_year", "paper_confidence"], as_index=False)
            .agg(roster_work_rows=("work_id", "size"), works_count=("work_id", "nunique"))
            .sort_values(["publication_year", "paper_confidence"])
        )
    else:
        agg["agg_confidence_by_year"] = pd.DataFrame()
    return agg


def save_tables(
    tables: dict[str, pd.DataFrame],
    aggregates: dict[str, pd.DataFrame],
    output_dir: Path,
    output_suffix: str,
    dataset_key: str,
    csv_output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, df in tables.items():
        path = _path_with_suffix(output_dir, name, output_suffix)
        df.to_parquet(path, index=False)
        paths[name] = path
    agg_dir = output_dir / "aggregates"
    agg_dir.mkdir(exist_ok=True)
    for name, df in aggregates.items():
        path = _path_with_suffix(agg_dir, name, output_suffix)
        df.to_parquet(path, index=False)
        paths[name] = path

    pub_csv = _csv_path(dataset_key, csv_output_dir)
    if not tables["roster_works"].empty:
        export = tables["roster_works"].merge(
            tables["works"].drop(columns=["title", "publication_year", "publication_date"], errors="ignore"),
            on="work_id",
            how="left",
        )
        export.to_csv(pub_csv, index=False)
    else:
        tables["roster_works"].to_csv(pub_csv, index=False)
    paths["scraped_publications_csv"] = pub_csv
    return paths


def build_cache_from_staff_csv(
    input_csv: Path | str,
    dataset_key: str = "demography",
    cache_dir: Path | str = CACHE_DIR,
    output_dir: Path | str = OUTPUT_DIR,
    mailto: str | None = None,
    max_candidates_per_person: int = 2,
    min_author_score: float = 0.55,
    throttle_s: float = 0.12,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    cfg = get_dataset_config(dataset_key)
    cache_dir = Path(cache_dir)
    output_dir = Path(output_dir)
    staff_df = read_staff_csv(input_csv)
    _log(progress, f"Loaded staff CSV rows: {len(staff_df):,}")

    client = OpenAlexClient(mailto=mailto, throttle_s=throttle_s)
    candidate_df, chosen = choose_author_matches(
        staff_df=staff_df,
        client=client,
        max_candidates_per_person=max_candidates_per_person,
        min_author_score=min_author_score,
        progress=progress,
    )
    _log(progress, f"Selected author candidates for work fetching: {len(chosen):,}")
    tables = build_tables(staff_df, chosen, client, progress=progress)
    tables["author_candidates"] = candidate_df
    aggregates = build_aggregates(tables)
    paths = save_tables(
        tables=tables,
        aggregates=aggregates,
        output_dir=cache_dir,
        output_suffix=cfg["suffix"],
        dataset_key=dataset_key,
        csv_output_dir=output_dir,
    )
    _log(progress, "Saved generated cache and scraped publication CSV.")
    return {"tables": tables, "aggregates": aggregates, "paths": paths, "dataset": cfg}


def find_default_staff_csv(dataset_key: str) -> Path | None:
    cfg = get_dataset_config(dataset_key)
    for key in ["default_staff_csv", "legacy_staff_csv"]:
        path = Path(cfg[key])
        if path.exists():
            return path
    template = Path(cfg["default_staff_csv"])
    if template.exists():
        return template
    return None
