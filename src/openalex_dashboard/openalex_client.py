from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, Iterator, Optional

import requests

OPENALEX_API = "https://api.openalex.org"
DEFAULT_THROTTLE_S = 0.12
DEFAULT_MAX_RETRIES = 6


class OpenAlexClient:
    """Small resilient OpenAlex API client used by the app and the CLI builder."""

    def __init__(
        self,
        mailto: str | None = None,
        throttle_s: float = DEFAULT_THROTTLE_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.mailto = (mailto or os.environ.get("OPENALEX_MAILTO", "")).strip()
        self.throttle_s = throttle_s
        self.max_retries = max_retries
        self.session = requests.Session()
        ua = "openalex-publications-dashboard/2.0"
        if self.mailto:
            ua = f"{ua} ({self.mailto})"
        self.session.headers.update({"User-Agent": ua})

    def _params(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        out = dict(params or {})
        if self.mailto:
            out["mailto"] = self.mailto
        return out

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = endpoint if endpoint.startswith("http") else f"{OPENALEX_API.rstrip('/')}/{endpoint.lstrip('/')}"
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.throttle_s > 0:
                    time.sleep(self.throttle_s)
                resp = self.session.get(url, params=self._params(params), timeout=120, allow_redirects=True)
                if resp.status_code in {429, 500, 502, 503, 504}:
                    wait = min(2 ** (attempt - 1), 60)
                    print(f"[OpenAlex retry {attempt}/{self.max_retries}] {resp.status_code}; sleeping {wait}s: {url}")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # pragma: no cover - network dependent
                last_err = exc
                if attempt == self.max_retries:
                    break
                wait = min(2 ** (attempt - 1), 60)
                print(f"[OpenAlex retry {attempt}/{self.max_retries}] {exc}; sleeping {wait}s: {url}")
                time.sleep(wait)
        raise RuntimeError(f"OpenAlex request failed after {self.max_retries} attempts: {url}\nLast error: {last_err}")

    def search_authors(self, query: str, per_page: int = 10) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        data = self.get(
            "authors",
            params={
                "search": query.strip(),
                "per_page": per_page,
                "select": ",".join(
                    [
                        "id",
                        "ids",
                        "display_name",
                        "display_name_alternatives",
                        "works_count",
                        "cited_by_count",
                        "last_known_institutions",
                        "affiliations",
                        "summary_stats",
                        "counts_by_year",
                    ]
                ),
            },
        )
        return data.get("results", []) or []

    def fetch_author(self, author_id: str) -> dict[str, Any]:
        return self.get(f"authors/{author_id}")

    def iter_works_for_author(self, author_id: str, per_page: int = 100) -> Iterator[dict[str, Any]]:
        cursor = "*"
        while True:
            data = self.get(
                "works",
                params={
                    "filter": f"authorships.author.id:{author_id}",
                    "per_page": per_page,
                    "cursor": cursor,
                    "select": ",".join(
                        [
                            "id",
                            "ids",
                            "doi",
                            "display_name",
                            "publication_year",
                            "publication_date",
                            "type",
                            "cited_by_count",
                            "authorships",
                            "primary_location",
                            "best_oa_location",
                            "open_access",
                            "topics",
                            "primary_topic",
                            "language",
                            "biblio",
                        ]
                    ),
                },
            )
            page = data.get("results", []) or []
            for item in page:
                yield item
            next_cursor = (data.get("meta") or {}).get("next_cursor")
            if not next_cursor or not page:
                break
            cursor = next_cursor


def batched(items: list[str], batch_size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]
