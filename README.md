# OpenAlex Publications Dashboard

A cache-first Streamlit dashboard for exploring publications, collaborators, topics, and sources for a roster of people linked to OpenAlex author IDs.

It now supports two department views from the same app:

* Demography using the standard cache filenames
* NDPH using the matching `*_ndph.parquet` cache filenames

The department switch appears at the top-left of the app. Changing it switches the cache used for all filters, plots, tables, and branding.

## Repository layout

```text
openalex_dashboard_repo/
├── app.py
├── requirements.txt
├── .streamlit/
│   └── config.toml
├── data/
│   ├── raw/
│   │   └── demography_openalex_people.csv
│   └── cache/
│       ├── .gitkeep
│       └── README.md
├── scripts/
│   └── build_openalex_cache.py
├── src/
│   └── openalex_dashboard/
│       ├── config.py
│       ├── data.py
│       ├── filters.py
│       └── views/
│           ├── overview.py
│           ├── domains_sources.py
│           ├── collaborators.py
│           ├── explorer.py
│           └── data_quality.py
└── tests/
    ├── conftest.py
    ├── test_dataset_switch.py
    └── test_helpers.py
```

## Cache naming convention

### Demography cache

```text
data/cache/people.parquet
data/cache/works.parquet
data/cache/authorships.parquet
data/cache/institutions.parquet
data/cache/topics_long.parquet
data/cache/aggregates/agg_publications_by_year.parquet
data/cache/aggregates/agg_citations_by_pubyear.parquet
data/cache/aggregates/agg_collaborator_countries_by_year.parquet
data/cache/aggregates/agg_domains_by_year.parquet
data/cache/aggregates/agg_sources_by_year.parquet
```

### NDPH cache

```text
data/cache/people_ndph.parquet
data/cache/works_ndph.parquet
data/cache/authorships_ndph.parquet
data/cache/institutions_ndph.parquet
data/cache/topics_long_ndph.parquet
data/cache/aggregates/agg_publications_by_year_ndph.parquet
data/cache/aggregates/agg_citations_by_pubyear_ndph.parquet
data/cache/aggregates/agg_collaborator_countries_by_year_ndph.parquet
data/cache/aggregates/agg_domains_by_year_ndph.parquet
data/cache/aggregates/agg_sources_by_year_ndph.parquet
```

## Quick start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Build the cache

Set your OpenAlex mailto value and run the build script:

```bash
export OPENALEX_MAILTO="xxx@ndph.ox.ac.uk"
python scripts/build_openalex_cache.py --input_csv data/raw/demography_openalex_people.csv --output_dir data/cache
```

For the NDPH version, place the generated files in the same `data/cache/` folder using the `*_ndph.parquet` naming convention.

### 3. Run the dashboard

```bash
streamlit run app.py
```

The dashboard should open on `http://localhost:8501`.

## Notes on architecture

* `scripts/build_openalex_cache.py` is the only place that talks to OpenAlex.
* `src/openalex_dashboard/data.py` resolves dataset-specific cache filenames and loads the local tables.
* `src/openalex_dashboard/filters.py` applies the global UI filters to the selected department bundle.
* Each file under `src/openalex_dashboard/views/` renders one dashboard section.
