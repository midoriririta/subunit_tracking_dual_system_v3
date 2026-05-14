from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.openalex_dashboard.cache_builder import build_cache_from_staff_csv, find_default_staff_csv
from src.openalex_dashboard.config import (
    BASE_PAGE_TITLE,
    CACHE_DIR,
    DATASET_CONFIGS,
    DEFAULT_DATASET_KEY,
    DEFAULT_OPENALEX_MAILTO,
    OUTPUT_DIR,
    RAW_DIR,
    get_dataset_display_order,
)
from src.openalex_dashboard.data import cache_status, clear_streamlit_cache, load_bundle
from src.openalex_dashboard.filters import apply_global_filters, render_sidebar_filters
from src.openalex_dashboard.views.collaborators import render_collaborators_tab
from src.openalex_dashboard.views.data_quality import render_data_quality_tab
from src.openalex_dashboard.views.domains_sources import render_domains_sources_tab
from src.openalex_dashboard.views.explorer import render_explorer_tab
from src.openalex_dashboard.views.overview import render_overview_tab

st.set_page_config(page_title=BASE_PAGE_TITLE, page_icon="📚", layout="wide")

BAD_SNAPSHOT_MARKER = "staff_recent_publications_json"


def sync_browser_title(title: str) -> None:
    """Keep the browser tab title aligned with the selected organisational view."""
    safe_title = title.replace("\\", "\\\\").replace("'", "\\'")
    components.html(
        f"""
        <script>
        window.parent.document.title = '{safe_title}';
        </script>
        """,
        height=0,
        width=0,
    )


def read_selected_dataset() -> str:
    """Read the selected dataset from the URL query parameter."""
    params = st.query_params
    dataset_key = params.get("dataset", DEFAULT_DATASET_KEY)
    if isinstance(dataset_key, list):
        dataset_key = dataset_key[0]
    dataset_key = str(dataset_key).lower()
    if dataset_key not in DATASET_CONFIGS:
        dataset_key = DEFAULT_DATASET_KEY
    return dataset_key


def append_progress(message: str) -> None:
    st.session_state.setdefault("build_log", []).append(message)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except Exception:
        return str(path)


def _dataset_nav_label(dataset_key: str) -> str:
    cfg = DATASET_CONFIGS[dataset_key]
    return cfg.get("navigation_label") or cfg.get("label", dataset_key)


def render_dataset_selector(current_dataset_key: str) -> str:
    """Render a hierarchy-aware dataset switcher.

    The Demographic Science Unit is intentionally shown as a subunit of the
    Nuffield Department of Population Health rather than as a parallel
    department-level choice.
    """
    dataset_options = get_dataset_display_order()
    if current_dataset_key not in dataset_options:
        current_dataset_key = DEFAULT_DATASET_KEY

    switch_col, _ = st.columns([1.25, 4], gap="small")
    with switch_col:
        selected_dataset_key = st.radio(
            "Organisation view",
            options=dataset_options,
            index=dataset_options.index(current_dataset_key),
            format_func=_dataset_nav_label,
            horizontal=False,
            label_visibility="visible",
        )
        st.caption("The Demographic Science Unit is shown as a subunit of NDPH.")

    if selected_dataset_key != current_dataset_key:
        st.query_params["dataset"] = selected_dataset_key
        st.rerun()

    return selected_dataset_key


def render_dataset_header(selected_cfg: dict) -> None:
    parent_label = selected_cfg.get("parent_label")
    if parent_label:
        st.markdown(
            f"""
            <div style="line-height:1.25; margin-top:0.3rem; margin-bottom:0.2rem;">
              <div style="font-size:0.95rem; color:rgba(49,51,63,0.72); font-weight:600;">
                {parent_label}
              </div>
              <div style="font-size:1.45rem; font-weight:750; padding-left:1.35rem;">
                ↳ {selected_cfg['label']}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.title(selected_cfg["title"])
    else:
        st.title(selected_cfg["title"])
    st.caption(selected_cfg["caption"])


def cache_looks_like_snapshot_cache(dataset_key: str) -> bool:
    """Detect the earlier lightweight cache built only from recent_publications_json.

    That snapshot was useful for a fast demo, but it is not the real scraped
    OpenAlex publication cache: it only contains staff-profile recent papers and
    lacks the full works/authorships/institutions/topics data. If this marker is
    present, the app should rebuild with the proper OpenAlex scraper.
    """
    status = cache_status(dataset_key)
    works_path = status["required"].get("works")
    if not works_path or not Path(works_path).exists():
        return False
    try:
        works = pd.read_parquet(works_path, columns=["snapshot_source"])
    except Exception:
        return False
    if "snapshot_source" not in works.columns or works.empty:
        return False
    return works["snapshot_source"].dropna().astype(str).eq(BAD_SNAPSHOT_MARKER).any()


def build_full_openalex_cache(
    dataset_key: str,
    input_csv: Path,
    mailto: str,
    max_candidates: int = 2,
    min_author_score: float = 0.55,
):
    st.session_state["build_log"] = []
    return build_cache_from_staff_csv(
        input_csv=input_csv,
        dataset_key=dataset_key,
        cache_dir=CACHE_DIR,
        output_dir=OUTPUT_DIR,
        mailto=mailto,
        max_candidates_per_person=int(max_candidates),
        min_author_score=float(min_author_score),
        progress=append_progress,
    )


def ensure_initial_full_cache(dataset_key: str) -> None:
    """Use an existing real cache; otherwise build the proper OpenAlex cache.

    The app should not re-scrape on every launch. It only builds automatically
    when required cache files are missing, or when it detects the old lightweight
    snapshot cache that was based on recent_publications_json.
    """
    status = cache_status(dataset_key)
    is_snapshot = cache_looks_like_snapshot_cache(dataset_key)
    if status["complete"] and not is_snapshot:
        return

    default_staff_csv = find_default_staff_csv(dataset_key)
    if not default_staff_csv:
        return

    reason = "cache is missing/incomplete" if not status["complete"] else "old snapshot cache detected"
    mailto = DEFAULT_OPENALEX_MAILTO or os.environ.get("OPENALEX_MAILTO", "")

    st.warning(
        f"The {status['dataset']['label']} publication cache needs a full OpenAlex build ({reason}). "
        "This happens only when the cache is missing or was built from the old staff-profile snapshot."
    )

    with st.spinner(
        f"Building full OpenAlex cache for {status['dataset']['label']} from "
        f"`{_display_path(default_staff_csv)}`..."
    ):
        try:
            result = build_full_openalex_cache(
                dataset_key=dataset_key,
                input_csv=default_staff_csv,
                mailto=mailto,
                max_candidates=2,
                min_author_score=0.55,
            )
        except Exception as exc:
            st.error(f"Automatic full OpenAlex cache build failed: {exc}")
            if st.session_state.get("build_log"):
                with st.expander("Build log", expanded=True):
                    st.code("\n".join(st.session_state["build_log"][-120:]))
            st.info(
                "Check that this environment has internet access, then rebuild from the sidebar at the end. "
                "The app will not use the old snapshot cache as if it were the real publication cache."
            )
            st.stop()

    clear_streamlit_cache()
    st.success("Full OpenAlex cache and scraped publication CSV generated.")
    paths = result.get("paths", {})
    if paths.get("scraped_publications_csv"):
        st.info(f"Publication CSV written to `{paths['scraped_publications_csv']}`")
    st.rerun()


def render_cache_update_panel(dataset_key: str) -> None:
    """Render update controls at the very end of the sidebar."""
    cfg = DATASET_CONFIGS[dataset_key]
    status = cache_status(dataset_key)
    default_staff_csv = find_default_staff_csv(dataset_key)
    is_snapshot = cache_looks_like_snapshot_cache(dataset_key)

    with st.sidebar:
        st.divider()
        with st.expander("Upload new staff CSV to update cache", expanded=False):
            if status["complete"] and not is_snapshot:
                st.success("Using existing full OpenAlex cache by default.")
            elif is_snapshot:
                st.warning("Old snapshot cache detected. Rebuild with full OpenAlex refresh.")
            else:
                st.warning("Cache missing: " + ", ".join(status["missing"]))

            if default_staff_csv:
                st.caption(f"Bundled staff CSV: `{_display_path(default_staff_csv)}`")
            else:
                st.caption(f"No bundled staff CSV found for {cfg['label']}.")

            uploaded = st.file_uploader(
                "Upload replacement staff CSV",
                type=["csv"],
                help=(
                    "Upload a staff/person CSV. The app will rebuild the full OpenAlex "
                    "publication cache only after you click the button below."
                ),
            )
            mailto = st.text_input(
                "OpenAlex mailto",
                value=DEFAULT_OPENALEX_MAILTO or os.environ.get("OPENALEX_MAILTO", ""),
                help="Optional but recommended for OpenAlex polite-pool requests.",
            )
            max_candidates = st.number_input(
                "Max OpenAlex author candidates per staff member",
                min_value=1,
                max_value=5,
                value=2,
                step=1,
            )
            min_author_score = st.slider(
                "Minimum author-match score to fetch works",
                min_value=0.0,
                max_value=1.0,
                value=0.55,
                step=0.05,
            )

            refresh_clicked = st.button("Update cache from uploaded CSV", use_container_width=True)
            rebuild_bundled_clicked = st.button("Rebuild cache from bundled raw CSV", use_container_width=True)

            if refresh_clicked:
                if uploaded is None:
                    st.error("Please upload a new staff CSV before updating the cache.")
                    st.stop()
                RAW_DIR.mkdir(parents=True, exist_ok=True)
                uploaded_path = RAW_DIR / f"{dataset_key}_uploaded_staff.csv"
                uploaded_path.write_bytes(uploaded.getvalue())

                with st.spinner("Rebuilding full OpenAlex cache from the uploaded staff CSV..."):
                    try:
                        result = build_full_openalex_cache(
                            dataset_key=dataset_key,
                            input_csv=uploaded_path,
                            mailto=mailto,
                            max_candidates=int(max_candidates),
                            min_author_score=float(min_author_score),
                        )
                    except Exception as exc:
                        st.error(f"OpenAlex cache update failed: {exc}")
                        if st.session_state.get("build_log"):
                            with st.expander("Build log", expanded=True):
                                st.code("\n".join(st.session_state["build_log"][-120:]))
                        st.stop()

                clear_streamlit_cache()
                st.success("Updated the publication CSV and parquet cache from the full OpenAlex refresh.")
                paths = result.get("paths", {})
                if paths.get("scraped_publications_csv"):
                    st.info(f"Publication CSV written to `{paths['scraped_publications_csv']}`")
                st.rerun()

            if rebuild_bundled_clicked:
                if not default_staff_csv:
                    st.error("No bundled raw staff CSV is available for this dataset.")
                    st.stop()

                with st.spinner("Rebuilding full OpenAlex cache from the bundled raw CSV..."):
                    try:
                        result = build_full_openalex_cache(
                            dataset_key=dataset_key,
                            input_csv=default_staff_csv,
                            mailto=mailto,
                            max_candidates=int(max_candidates),
                            min_author_score=float(min_author_score),
                        )
                    except Exception as exc:
                        st.error(f"OpenAlex cache rebuild failed: {exc}")
                        if st.session_state.get("build_log"):
                            with st.expander("Build log", expanded=True):
                                st.code("\n".join(st.session_state["build_log"][-120:]))
                        st.stop()

                clear_streamlit_cache()
                st.success("Rebuilt the full OpenAlex publication cache from the bundled raw CSV.")
                paths = result.get("paths", {})
                if paths.get("scraped_publications_csv"):
                    st.info(f"Publication CSV written to `{paths['scraped_publications_csv']}`")
                st.rerun()


def main() -> None:
    current_dataset_key = read_selected_dataset()
    selected_dataset_key = render_dataset_selector(current_dataset_key)
    selected_cfg = DATASET_CONFIGS[selected_dataset_key]

    sync_browser_title(selected_cfg["title"])
    render_dataset_header(selected_cfg)

    # First-launch / repaired-deployment behaviour:
    # use a real cache if present; otherwise build the full OpenAlex cache from data/raw.
    ensure_initial_full_cache(selected_dataset_key)

    try:
        bundle = load_bundle(selected_dataset_key)
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.info(
            "No full cache could be loaded or created. Check that the matching CSV exists in data/raw, "
            "or upload a staff CSV at the end of the sidebar to rebuild the cache."
        )
        render_cache_update_panel(selected_dataset_key)
        st.stop()

    filters = render_sidebar_filters(bundle)
    render_cache_update_panel(selected_dataset_key)
    filtered = apply_global_filters(bundle, filters)

    tab_overview, tab_domains, tab_collab, tab_explorer, tab_quality = st.tabs(
        [
            "Overview",
            "Domains & Sources",
            "Collaborators",
            "Publications Explorer",
            "Data Quality",
        ]
    )

    with tab_overview:
        render_overview_tab(bundle, filtered)
    with tab_domains:
        render_domains_sources_tab(bundle, filtered)
    with tab_collab:
        render_collaborators_tab(bundle, filtered)
    with tab_explorer:
        render_explorer_tab(bundle, filtered)
    with tab_quality:
        render_data_quality_tab(bundle, filtered)


if __name__ == "__main__":
    main()
