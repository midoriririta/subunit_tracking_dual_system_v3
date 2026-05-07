Place the generated cache files here. The app supports two parallel cache sets.

## Demography cache
```text
data/cache/
├── people.parquet
├── works.parquet
├── authorships.parquet
├── institutions.parquet
├── topics_long.parquet
└── aggregates/
    ├── agg_publications_by_year.parquet
    ├── agg_citations_by_pubyear.parquet
    ├── agg_collaborator_countries_by_year.parquet
    ├── agg_domains_by_year.parquet
    └── agg_sources_by_year.parquet
```

## NDPH cache
```text
data/cache/
├── people_ndph.parquet
├── works_ndph.parquet
├── authorships_ndph.parquet
├── institutions_ndph.parquet
├── topics_long_ndph.parquet
└── aggregates/
    ├── agg_publications_by_year_ndph.parquet
    ├── agg_citations_by_pubyear_ndph.parquet
    ├── agg_collaborator_countries_by_year_ndph.parquet
    ├── agg_domains_by_year_ndph.parquet
    └── agg_sources_by_year_ndph.parquet
```
