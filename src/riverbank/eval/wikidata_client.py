"""Wikidata SPARQL client for the evaluation framework.

Fetches Wikidata statements for entities via SPARQL, excluding external
identifiers, media files, and interwiki links — keeping only the semantic
triples that are directly comparable to riverbank's output.

User-Agent requirement
~~~~~~~~~~~~~~~~~~~~~~
Wikidata SPARQL requires a descriptive User-Agent::

    User-Agent: riverbank-eval/0.15.0 (trickle-labs/riverbank)

Requests without it are rejected with HTTP 403.

Retry policy
~~~~~~~~~~~~
- 3 attempts with exponential back-off (2 s, 4 s, 8 s).
- ``WikidataUnavailableError`` is raised when the endpoint is unreachable or
  returns a 5xx error after all retries.

Excluded property types
~~~~~~~~~~~~~~~~~~~~~~~
- ``wikibase:ExternalId`` — database IDs (IMDb, GND, …)
- ``wikibase:CommonsMedia`` — file references
- ``wikibase:Url`` — raw URLs
- ``wikibase:GlobeCoordinate`` coordinates are *included*; they contain
  semantic location information.
"""
from __future__ import annotations

import time
from urllib.parse import quote as urlquote

from riverbank.eval.models import WikidataItem, WikidataStatement

_USER_AGENT = (
    "riverbank-eval/0.15.0 "
    "(trickle-labs/riverbank; github.com/trickle-labs/riverbank)"
)
_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# SPARQL template: fetch all non-excluded statements for a single item
_ITEM_SPARQL_TEMPLATE = """
SELECT ?property ?propertyLabel ?value ?valueLabel ?valueType ?rank
WHERE {{
  wd:{qid} ?p ?statement .
  ?statement ?ps ?value .
  ?property wikibase:claim ?p ;
             wikibase:statementProperty ?ps ;
             wikibase:propertyType ?valueType .

  # Exclude external identifiers, media files, and raw URLs
  FILTER(?valueType NOT IN (
    wikibase:ExternalId,
    wikibase:CommonsMedia,
    wikibase:Url
  ))

  OPTIONAL {{ ?statement wikibase:rank ?rank . }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
ORDER BY ?propertyLabel
LIMIT 500
"""


class WikidataUnavailableError(RuntimeError):
    """Raised when the Wikidata SPARQL endpoint is unreachable."""


class WikidataClient:
    """Fetch Wikidata items and statements via SPARQL.

    Parameters
    ----------
    sparql_endpoint:
        URL of the SPARQL endpoint (default: ``https://query.wikidata.org/sparql``).
    max_retries:
        Number of retry attempts on transient errors.
    """

    def __init__(
        self,
        sparql_endpoint: str = _SPARQL_ENDPOINT,
        max_retries: int = 3,
    ) -> None:
        self.endpoint = sparql_endpoint
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_item_by_qid(self, qid: str) -> WikidataItem:
        """Fetch a Wikidata item and all its non-excluded statements."""
        label, description, aliases = self._fetch_labels(qid)
        statements = self._fetch_statements(qid)
        return WikidataItem(
            qid=qid,
            label=label,
            description=description,
            aliases=aliases,
            statements=statements,
        )

    def get_item_by_wikipedia_title(
        self, title: str, language: str = "en"
    ) -> WikidataItem:
        """Resolve an English Wikipedia title to a Wikidata item."""
        qid = self._resolve_sitelink(title, language)
        if not qid:
            return WikidataItem(qid="", label=title, description="", aliases=[], statements=[])
        return self.get_item_by_qid(qid)

    def query_sparql(self, sparql: str, timeout: int = 60) -> list[dict]:
        """Execute a SPARQL query and return rows as dicts.

        Retries up to ``self.max_retries`` times with exponential back-off.

        Raises
        ------
        WikidataUnavailableError
            If all retries fail.
        """
        try:
            import requests  # noqa: PLC0415
        except ImportError as exc:
            raise WikidataUnavailableError(
                "requests is required for Wikidata queries. "
                "Install with: pip install 'riverbank[eval]'"
            ) from exc

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.get(
                    self.endpoint,
                    params={"query": sparql, "format": "json"},
                    headers={
                        "User-Agent": _USER_AGENT,
                        "Accept": "application/sparql-results+json",
                    },
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                bindings = data.get("results", {}).get("bindings", [])
                return [self._binding_to_dict(b) for b in bindings]
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))  # 2, 4, 8 seconds

        raise WikidataUnavailableError(
            f"Wikidata SPARQL endpoint unreachable after {self.max_retries} retries: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_statements(self, qid: str) -> list[WikidataStatement]:
        sparql = _ITEM_SPARQL_TEMPLATE.format(qid=qid)
        try:
            rows = self.query_sparql(sparql)
        except WikidataUnavailableError:
            return []

        return self._filter_statements(rows)

    def _filter_statements(self, rows: list[dict]) -> list[WikidataStatement]:
        """Convert SPARQL result rows to WikidataStatement objects."""
        statements = []
        for row in rows:
            prop_id = row.get("property", "")
            # Only keep P-id style properties
            if not prop_id.startswith("P"):
                continue
            value = row.get("value", "")
            if not value:
                continue

            value_type = row.get("valueType", "string")
            # Simplify type URI to short label
            if "ExternalId" in value_type or "CommonsMedia" in value_type or "Url" in value_type:
                continue  # redundant safety filter

            value_type_short = self._simplify_type(value_type)
            value_label = row.get("valueLabel", None)
            if value_label == value:
                value_label = None

            rank_uri = row.get("rank", "")
            rank = "preferred" if "Preferred" in rank_uri else (
                "deprecated" if "Deprecated" in rank_uri else "normal"
            )

            statements.append(
                WikidataStatement(
                    property_id=prop_id,
                    property_label=row.get("propertyLabel", prop_id),
                    value=value,
                    value_type=value_type_short,
                    value_label=value_label or None,
                    rank=rank,
                )
            )
        return statements

    def _fetch_labels(self, qid: str) -> tuple[str, str, list[str]]:
        """Fetch label, description, and aliases for a Q-id via Wikidata API."""
        try:
            import requests  # noqa: PLC0415

            params = {
                "action": "wbgetentities",
                "ids": qid,
                "props": "labels|descriptions|aliases",
                "languages": "en",
                "format": "json",
            }
            resp = requests.get(
                _WIKIDATA_API,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            data = resp.json()
            entity = data.get("entities", {}).get(qid, {})

            labels = entity.get("labels", {})
            label = labels.get("en", {}).get("value", qid)

            descs = entity.get("descriptions", {})
            description = descs.get("en", {}).get("value", "")

            aliases_raw = entity.get("aliases", {}).get("en", [])
            aliases = [a.get("value", "") for a in aliases_raw]

            return label, description, aliases
        except Exception:  # noqa: BLE001
            return qid, "", []

    def _resolve_sitelink(self, title: str, language: str = "en") -> str:
        """Resolve Wikipedia article title to Wikidata Q-id via sitelink."""
        try:
            import requests  # noqa: PLC0415

            params = {
                "action": "query",
                "titles": title,
                "prop": "pageprops",
                "ppprop": "wikibase_item",
                "format": "json",
            }
            resp = requests.get(
                f"https://{language}.wikipedia.org/w/api.php",
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=15,
            )
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                qid = page.get("pageprops", {}).get("wikibase_item", "")
                if qid:
                    return qid
            return ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _binding_to_dict(binding: dict) -> dict:
        """Flatten a SPARQL result binding to a flat string dict."""
        result: dict[str, str] = {}
        for key, val in binding.items():
            raw_value = val.get("value", "")
            # Shorten Q-id or P-id URIs
            if "wikidata.org/entity/Q" in raw_value:
                raw_value = raw_value.rsplit("/", 1)[-1]  # "Q123"
            elif "wikidata.org/entity/P" in raw_value:
                raw_value = raw_value.rsplit("/", 1)[-1]  # "P31"
            elif "wikidata.org/prop/" in raw_value:
                raw_value = raw_value.rsplit("/", 1)[-1]
            result[key] = raw_value
        return result

    @staticmethod
    def _simplify_type(type_uri: str) -> str:
        """Map full wikibase type URI to a short name."""
        mapping = {
            "WikibaseItem": "wikibase-item",
            "String": "string",
            "Quantity": "quantity",
            "Time": "time",
            "Monolingualtext": "monolingualtext",
            "GlobeCoordinate": "globe-coordinate",
            "Math": "math",
            "MusicalNotation": "musical-notation",
        }
        for suffix, short in mapping.items():
            if suffix in type_uri:
                return short
        return "string"
