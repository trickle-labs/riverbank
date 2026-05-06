from __future__ import annotations

"""Federated compilation via SPARQL SERVICE (v0.9.0).

A "remote profile" type that pulls SERVICE-federated triples from a peer
``pg_ripple`` instance into a local compilation context, applies confidence
weighting, and writes the result locally.

The SPARQL ``SERVICE`` keyword is implemented in pg-ripple's query engine.
riverbank's contribution is:
- A ``FederationEndpoint`` configuration type.
- A ``remote_profile`` flag in compiler profiles.
- SQL to register ``federation_endpoints`` via ``tide.relay_inlet_config``.
- A ``federated_compile`` helper that issues the SERVICE query and writes
  results locally.

No federation protocol code lives in riverbank; this module configures
endpoints and dispatches standard SPARQL queries.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FederationEndpoint:
    """Configuration for a remote pg_ripple SPARQL endpoint.

    Attributes:
        name:            Logical name for this endpoint (used in profiles).
        sparql_url:      Full URL to the remote SPARQL endpoint.
        named_graph:     Remote named graph IRI to query.
        confidence_weight: Weight applied to remote facts (0.0–1.0).
                           Remote facts are typically down-weighted relative
                           to locally compiled facts.
        timeout_seconds: Query timeout.
    """

    name: str
    sparql_url: str
    named_graph: str = "http://riverbank.example/graph/trusted"
    confidence_weight: float = 0.8
    timeout_seconds: int = 30


@dataclass
class FederationResult:
    """Result of a federated compilation step.

    Attributes:
        endpoint_name: Name of the federation endpoint queried.
        triples_fetched: Number of triples received from the remote.
        triples_written: Number of triples written locally.
        success:        Whether the operation succeeded.
        error:          Error message when success is False.
    """

    endpoint_name: str
    triples_fetched: int = 0
    triples_written: int = 0
    success: bool = True
    error: str = ""


# ---------------------------------------------------------------------------
# Endpoint registration
# ---------------------------------------------------------------------------

def register_federation_endpoint(conn: Any, endpoint: FederationEndpoint) -> bool:
    """Register a federation endpoint in the catalog.

    Creates ``_riverbank.federation_endpoints`` if needed, then upserts
    the endpoint row.  pg-ripple picks up the endpoint configuration via
    ``tide.relay_inlet_config`` on the next ``NOTIFY`` hot reload.

    Returns ``True`` on success.
    """
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _riverbank.federation_endpoints (
                id                SERIAL PRIMARY KEY,
                name              TEXT UNIQUE NOT NULL,
                sparql_url        TEXT NOT NULL,
                named_graph       TEXT NOT NULL DEFAULT 'http://riverbank.example/graph/trusted',
                confidence_weight DOUBLE PRECISION NOT NULL DEFAULT 0.8,
                timeout_seconds   INTEGER NOT NULL DEFAULT 30,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            INSERT INTO _riverbank.federation_endpoints
                (name, sparql_url, named_graph, confidence_weight, timeout_seconds)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
              SET sparql_url        = EXCLUDED.sparql_url,
                  named_graph       = EXCLUDED.named_graph,
                  confidence_weight = EXCLUDED.confidence_weight,
                  timeout_seconds   = EXCLUDED.timeout_seconds,
                  updated_at        = now()
            """,
            (
                endpoint.name,
                endpoint.sparql_url,
                endpoint.named_graph,
                endpoint.confidence_weight,
                endpoint.timeout_seconds,
            ),
        )
        logger.info("Federation endpoint registered: %s -> %s", endpoint.name, endpoint.sparql_url)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to register federation endpoint %s: %s", endpoint.name, exc)
        return False


def list_federation_endpoints(conn: Any) -> list[FederationEndpoint]:
    """Return all registered federation endpoints.

    Returns an empty list when the table does not exist.
    """
    try:
        rows = conn.execute(
            "SELECT name, sparql_url, named_graph, confidence_weight, timeout_seconds "
            "FROM _riverbank.federation_endpoints ORDER BY name"
        ).fetchall()
        return [
            FederationEndpoint(
                name=r[0],
                sparql_url=r[1],
                named_graph=r[2],
                confidence_weight=float(r[3]),
                timeout_seconds=int(r[4]),
            )
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list federation endpoints: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Federated compilation
# ---------------------------------------------------------------------------

def build_service_query(endpoint: FederationEndpoint, limit: int = 1000) -> str:
    """Build a SPARQL SERVICE query targeting a remote named graph.

    The query fetches ``(subject, predicate, object)`` triples from the remote
    endpoint's named graph using the ``SERVICE`` keyword.  pg-ripple's query
    engine handles the federation protocol.

    Returns the SPARQL query string.
    """
    return (
        "SELECT ?subject ?predicate ?object WHERE {\n"
        f"  SERVICE <{endpoint.sparql_url}> {{\n"
        f"    GRAPH <{endpoint.named_graph}> {{\n"
        "      ?subject ?predicate ?object .\n"
        "    }\n"
        "  }\n"
        f"}} LIMIT {limit}"
    )


def federated_compile(
    conn: Any,
    endpoint: FederationEndpoint,
    local_named_graph: str = "http://riverbank.example/graph/trusted",
    limit: int = 1000,
) -> FederationResult:
    """Pull triples from a remote endpoint and write them locally.

    Issues a SPARQL SERVICE query via pg-ripple.  Applies the endpoint's
    ``confidence_weight`` to each fetched triple before writing it locally
    via ``pg_ripple.load_triples_with_confidence()``.

    Falls back gracefully when pg-ripple's SERVICE federation is unavailable.
    """
    import json as _json  # noqa: PLC0415

    sparql = build_service_query(endpoint, limit=limit)

    # Step 1: fetch remote triples via pg_ripple.sparql_query
    try:
        rows = conn.execute(
            "SELECT * FROM pg_ripple.sparql_query($1)",
            (sparql,),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        logger.warning(
            "federated_compile: SERVICE query failed for %s: %s",
            endpoint.name, msg,
        )
        return FederationResult(
            endpoint_name=endpoint.name,
            success=False,
            error=msg,
        )

    triples_fetched = len(rows)
    if not rows:
        return FederationResult(
            endpoint_name=endpoint.name,
            triples_fetched=0,
            triples_written=0,
            success=True,
        )

    # Step 2: write triples locally with confidence weighting
    payload = [
        {
            "subject": str(r[0]),
            "predicate": str(r[1]),
            "object": str(r[2]),
            "confidence": endpoint.confidence_weight,
            "source": endpoint.sparql_url,
        }
        for r in rows
    ]

    try:
        conn.execute(
            "SELECT pg_ripple.load_triples_with_confidence($1, $2)",
            (_json.dumps(payload), local_named_graph),
        )
        triples_written = len(payload)
        logger.info(
            "federated_compile: wrote %d triples from %s",
            triples_written,
            endpoint.name,
        )
        return FederationResult(
            endpoint_name=endpoint.name,
            triples_fetched=triples_fetched,
            triples_written=triples_written,
            success=True,
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        logger.warning("federated_compile: write failed for %s: %s", endpoint.name, msg)
        return FederationResult(
            endpoint_name=endpoint.name,
            triples_fetched=triples_fetched,
            triples_written=0,
            success=False,
            error=msg,
        )
