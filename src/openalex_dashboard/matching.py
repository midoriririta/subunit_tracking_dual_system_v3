from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional

import pandas as pd

try:  # rapidfuzz is faster and better, but keep a fallback for portability.
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    fuzz = None

from src.openalex_dashboard.config import OXFORD_TERMS


def safe_json(obj: Any) -> str | None:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return None


def norm_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    value = str(value).strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalise_openalex_author_id(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value = str(value).strip()
    if not value:
        return None
    match = re.search(r"(A\d+)$", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"A\d+", value):
        return value
    return None


def normalise_orcid(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    value = str(value).strip()
    value = value.replace("https://orcid.org/", "").replace("http://orcid.org/", "")
    return value.lower()


def name_similarity(a: Any, b: Any) -> float:
    a_norm = norm_text(a)
    b_norm = norm_text(b)
    if not a_norm or not b_norm:
        return 0.0
    if fuzz is not None:
        return float(fuzz.token_set_ratio(a_norm, b_norm)) / 100.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def collect_institution_strings(author_or_work_obj: Any) -> list[str]:
    """Collect possible institution strings from OpenAlex author or authorship objects."""
    out: list[str] = []

    def add_inst(inst: dict[str, Any]) -> None:
        for key in ["display_name", "ror", "id", "country_code", "type"]:
            value = inst.get(key)
            if value:
                out.append(str(value))

    if not author_or_work_obj:
        return out

    if isinstance(author_or_work_obj, dict):
        for inst in author_or_work_obj.get("last_known_institutions") or []:
            add_inst(inst)
        for aff in author_or_work_obj.get("affiliations") or []:
            if aff.get("institution"):
                add_inst(aff["institution"])
            for inst in aff.get("institutions") or []:
                add_inst(inst)
        for inst in author_or_work_obj.get("institutions") or []:
            add_inst(inst)
    return out


def has_oxford_text(values: Iterable[Any], extra_terms: Iterable[str] = ()) -> bool:
    terms = [norm_text(x) for x in list(OXFORD_TERMS) + list(extra_terms) if norm_text(x)]
    blob = " | ".join(norm_text(x) for x in values if norm_text(x))
    return any(term and term in blob for term in terms)


def extract_staff_fields(row: pd.Series) -> dict[str, Any]:
    cols = {str(c).lower().strip(): c for c in row.index}

    def first(*names: str) -> Any:
        for name in names:
            if name.lower() in cols:
                value = row[cols[name.lower()]]
                if value is not None and not (isinstance(value, float) and pd.isna(value)) and str(value).strip():
                    return value
        return ""

    return {
        "name": first("name", "full_name", "person_name", "display_name", "staff_name"),
        "email": first("email", "email_address", "mail"),
        "orcid": first("orcid", "orcid_id"),
        "openalex_author_id": first("openalex_author_id", "author_id", "openalex_id"),
        "primary_institution": first("primary_institution", "institution", "affiliation", "organisation", "organization"),
        "department": first("department", "dept", "unit"),
        "subunit": first("subunit", "group", "team"),
        "start_year": first("start_year", "appointment_start_year", "from_year", "year_start"),
        "end_year": first("end_year", "appointment_end_year", "to_year", "year_end"),
    }


def parse_year(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    if not match:
        return None
    return int(match.group(0))


@dataclass
class AuthorMatch:
    staff_index: int
    staff_name: str
    openalex_author_id_short: str
    openalex_author_id_full: str
    author_display_name: str
    score: float
    confidence: str
    reasons: list[str]
    record: dict[str, Any]


def score_author_candidate(staff: dict[str, Any], author_record: dict[str, Any], explicit_id: bool = False) -> tuple[float, str, list[str]]:
    reasons: list[str] = []
    staff_name = staff.get("name", "")
    author_name = author_record.get("display_name", "")
    score = 0.0

    if explicit_id:
        score += 0.72
        reasons.append("staff row supplied this OpenAlex author ID")

    staff_orcid = normalise_orcid(staff.get("orcid"))
    author_orcid = normalise_orcid((author_record.get("ids") or {}).get("orcid"))
    if staff_orcid and author_orcid and staff_orcid == author_orcid:
        score += 0.85
        reasons.append("ORCID matches exactly")

    sim = name_similarity(staff_name, author_name)
    if sim >= 0.97:
        score += 0.28
        reasons.append("name matches exactly or near-exactly")
    elif sim >= 0.90:
        score += 0.22
        reasons.append("name is a strong fuzzy match")
    elif sim >= 0.78:
        score += 0.12
        reasons.append("name is a partial fuzzy match")
    else:
        reasons.append("name similarity is weak")

    staff_terms = [staff.get("primary_institution"), staff.get("department"), staff.get("subunit")]
    inst_values = collect_institution_strings(author_record)
    if has_oxford_text(inst_values, staff_terms):
        score += 0.18
        reasons.append("OpenAlex author profile has Oxford/unit affiliation evidence")

    works_count = author_record.get("works_count") or 0
    try:
        works_count = int(works_count)
    except Exception:
        works_count = 0
    if works_count > 0:
        score += 0.02

    score = max(0.0, min(score, 1.0))
    if score >= 0.86:
        band = "high"
    elif score >= 0.68:
        band = "medium"
    else:
        band = "low"
    return score, band, reasons


def score_work_for_staff(
    staff: dict[str, Any],
    author_match_score: float,
    author_match_confidence: str,
    work: dict[str, Any],
    authorship: dict[str, Any],
) -> dict[str, Any]:
    """Return paper-level confidence for a staff member/work pair.

    Core principle: a reliable author match is necessary but not sufficient for high
    confidence. High confidence requires paper-level Oxford/unit evidence in that
    work's authorship, not only a person-level match.
    """
    reasons: list[str] = []
    staff_name = staff.get("name", "")
    author = authorship.get("author") or {}
    raw_author_name = authorship.get("raw_author_name") or author.get("display_name") or ""
    sim = name_similarity(staff_name, raw_author_name)

    if sim >= 0.95:
        name_score = 1.0
        reasons.append("work authorship name matches staff name")
    elif sim >= 0.85:
        name_score = 0.75
        reasons.append("work authorship name is a good fuzzy match")
    else:
        name_score = 0.35
        reasons.append("work authorship name is weak/ambiguous")

    staff_terms = [staff.get("primary_institution"), staff.get("department"), staff.get("subunit")]
    inst_values = collect_institution_strings(authorship)
    raw_affiliations = authorship.get("raw_affiliation_strings") or []
    inst_values.extend(raw_affiliations)
    strong_oxford_affiliation = has_oxford_text(inst_values, staff_terms)

    if strong_oxford_affiliation:
        affiliation_score = 1.0
        reasons.append("paper authorship has Oxford/unit affiliation evidence")
    elif inst_values:
        affiliation_score = 0.35
        reasons.append("paper has affiliation metadata, but not clear Oxford/unit evidence")
    else:
        affiliation_score = 0.25
        reasons.append("paper authorship has no usable affiliation metadata")

    pub_year = parse_year(work.get("publication_year"))
    start_year = parse_year(staff.get("start_year"))
    end_year = parse_year(staff.get("end_year"))
    if pub_year is None:
        time_score = 0.50
        reasons.append("publication year is missing")
    else:
        lower_ok = start_year is None or pub_year >= start_year - 1
        upper_ok = end_year is None or pub_year <= end_year + 1
        if lower_ok and upper_ok:
            time_score = 1.0
            reasons.append("publication year is compatible with staff appointment window")
        elif start_year and pub_year < start_year - 1:
            time_score = 0.20
            reasons.append("publication appears before the appointment window")
        elif end_year and pub_year > end_year + 1:
            time_score = 0.35
            reasons.append("publication appears after the appointment window")
        else:
            time_score = 0.55
            reasons.append("appointment-window evidence is incomplete")

    score = (
        0.48 * author_match_score
        + 0.32 * affiliation_score
        + 0.12 * time_score
        + 0.08 * name_score
    )

    if authorship.get("is_corresponding") is True:
        score += 0.02
        reasons.append("staff author is marked as corresponding author")

    # Important caps: without paper-level Oxford/unit evidence, a paper should not
    # become high confidence merely because the OpenAlex person is correct.
    if not strong_oxford_affiliation:
        score = min(score, 0.81)
    if time_score < 0.40:
        score = min(score, 0.69)
    if author_match_confidence == "low":
        score = min(score, 0.59)

    score = max(0.0, min(score, 1.0))
    if score >= 0.84 and strong_oxford_affiliation and author_match_score >= 0.80:
        confidence = "high"
    elif score >= 0.62:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "paper_confidence": confidence,
        "paper_confidence_score": round(score, 4),
        "paper_confidence_reasons": "; ".join(dict.fromkeys(reasons)),
        "paper_has_oxford_affiliation": bool(strong_oxford_affiliation),
        "paper_affiliation_score": round(affiliation_score, 4),
        "paper_time_score": round(time_score, 4),
        "paper_name_score": round(name_score, 4),
    }
