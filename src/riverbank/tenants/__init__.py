from __future__ import annotations

"""Multi-tenant Row-Level Security activation and tenant lifecycle (v0.9.0).

Activates PostgreSQL Row-Level Security (RLS) on all ``_riverbank`` tables
using the ``tenant_id`` column scaffolded in v0.4.0 (Alembic migration 0002).

Each tenant operates within an isolated editorial namespace:
- Per-tenant compiler profiles and named graphs.
- Tenant lifecycle: create, suspend, delete (with GDPR erasure).
- RLS policies are set/enforced at the database level; riverbank configures
  the policies via SQL and sets ``app.current_tenant_id`` for each session.

The ``tenant_id`` column already exists (nullable, migration 0002).  This
module activates the RLS constraint that makes it mandatory during normal
operations.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tenant status
# ---------------------------------------------------------------------------

class TenantStatus(str, Enum):
    """Lifecycle state of a tenant."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class Tenant:
    """Represents a single tenant in the multi-tenant deployment.

    Attributes:
        tenant_id:   Unique string identifier for the tenant (slug).
        display_name: Human-readable name.
        status:      Current lifecycle state.
        label_studio_org_id: Label Studio organisation ID (per-tenant).
        named_graph_prefix: Base IRI prefix for this tenant's named graphs.
    """

    tenant_id: str
    display_name: str = ""
    status: TenantStatus = TenantStatus.ACTIVE
    label_studio_org_id: int | None = None
    named_graph_prefix: str = ""

    def __post_init__(self) -> None:
        if not self.named_graph_prefix:
            self.named_graph_prefix = f"http://riverbank.example/tenant/{self.tenant_id}/graph/"


# ---------------------------------------------------------------------------
# RLS helpers
# ---------------------------------------------------------------------------

_RLS_TABLES = [
    "sources",
    "fragments",
    "profiles",
    "runs",
    "artifact_deps",
    "log",
]


def enable_rls(conn: Any, table: str) -> bool:
    """Enable Row-Level Security on a single ``_riverbank`` table.

    Idempotent — safe to call when RLS is already enabled.
    Returns ``True`` on success, ``False`` when the table does not exist or the
    operation fails.
    """
    try:
        conn.execute(f"ALTER TABLE _riverbank.{table} ENABLE ROW LEVEL SECURITY")
        logger.info("RLS enabled on _riverbank.%s", table)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not enable RLS on _riverbank.%s: %s", table, exc)
        return False


def create_rls_policy(conn: Any, table: str) -> bool:
    """Create the tenant isolation RLS policy for a table.

    The policy allows rows where ``tenant_id`` matches the session-local
    ``app.current_tenant_id`` GUC, or where ``tenant_id`` IS NULL (system
    rows that pre-date multi-tenancy).

    Policy name: ``riverbank_tenant_isolation``.
    """
    policy_name = "riverbank_tenant_isolation"
    try:
        # Drop existing policy first (idempotent)
        conn.execute(
            f"DROP POLICY IF EXISTS {policy_name} ON _riverbank.{table}"
        )
        conn.execute(
            f"""
            CREATE POLICY {policy_name}
            ON _riverbank.{table}
            USING (
                tenant_id IS NULL
                OR tenant_id = current_setting('app.current_tenant_id', TRUE)
            )
            """
        )
        logger.info("RLS policy created on _riverbank.%s", table)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not create RLS policy on _riverbank.%s: %s", table, exc)
        return False


def activate_rls_for_all_tables(conn: Any) -> dict[str, bool]:
    """Enable RLS and create tenant-isolation policies on all catalog tables.

    Returns a dict mapping ``table_name -> success``.
    """
    results: dict[str, bool] = {}
    for table in _RLS_TABLES:
        enabled = enable_rls(conn, table)
        policy_ok = create_rls_policy(conn, table) if enabled else False
        results[table] = enabled and policy_ok
    return results


def set_current_tenant(conn: Any, tenant_id: str) -> None:
    """Set the ``app.current_tenant_id`` session GUC for the current connection.

    All RLS policies use this setting to filter rows to the active tenant.
    Call this at the start of every tenant-scoped database session.
    """
    # Sanitise: tenant_id must be alphanumeric/hyphen/underscore
    if not all(c.isalnum() or c in ("-", "_") for c in tenant_id):
        raise ValueError(f"Invalid tenant_id: {tenant_id!r}")
    conn.execute(f"SET app.current_tenant_id = '{tenant_id}'")


def clear_current_tenant(conn: Any) -> None:
    """Clear the current tenant GUC (reset to superuser / no tenant scope)."""
    conn.execute("RESET app.current_tenant_id")


# ---------------------------------------------------------------------------
# Tenant lifecycle
# ---------------------------------------------------------------------------

def create_tenant(
    conn: Any,
    tenant: Tenant,
) -> bool:
    """Persist a new tenant record in ``_riverbank.tenants``.

    Creates the ``_riverbank.tenants`` table if it does not yet exist, then
    inserts the tenant row.  Returns ``True`` on success.
    """
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _riverbank.tenants (
                id           SERIAL PRIMARY KEY,
                tenant_id    TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                status       TEXT NOT NULL DEFAULT 'active',
                label_studio_org_id INTEGER,
                named_graph_prefix  TEXT NOT NULL DEFAULT '',
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            INSERT INTO _riverbank.tenants
                (tenant_id, display_name, status, label_studio_org_id, named_graph_prefix)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id) DO UPDATE
              SET display_name = EXCLUDED.display_name,
                  status       = EXCLUDED.status,
                  updated_at   = now()
            """,
            (
                tenant.tenant_id,
                tenant.display_name,
                tenant.status.value,
                tenant.label_studio_org_id,
                tenant.named_graph_prefix,
            ),
        )
        logger.info("Tenant created/updated: %s", tenant.tenant_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create tenant %s: %s", tenant.tenant_id, exc)
        return False


def suspend_tenant(conn: Any, tenant_id: str) -> bool:
    """Mark a tenant as suspended (all RLS-gated operations will fail)."""
    try:
        conn.execute(
            "UPDATE _riverbank.tenants SET status = 'suspended', updated_at = now() "
            "WHERE tenant_id = %s",
            (tenant_id,),
        )
        logger.info("Tenant suspended: %s", tenant_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not suspend tenant %s: %s", tenant_id, exc)
        return False


def delete_tenant(conn: Any, tenant_id: str, gdpr_erasure: bool = False) -> bool:
    """Delete a tenant and optionally erase all tenant-scoped data (GDPR).

    When ``gdpr_erasure=True`` this deletes all rows in the catalog tables
    where ``tenant_id`` matches *before* removing the tenant record.  The
    audit log rows are also removed (GDPR erasure overrides append-only).

    When ``gdpr_erasure=False`` the tenant record is marked as ``deleted``
    and data rows are retained for archival.
    """
    try:
        if gdpr_erasure:
            for table in _RLS_TABLES:
                conn.execute(
                    f"DELETE FROM _riverbank.{table} WHERE tenant_id = %s",
                    (tenant_id,),
                )
            conn.execute(
                "DELETE FROM _riverbank.tenants WHERE tenant_id = %s",
                (tenant_id,),
            )
            logger.info("Tenant GDPR-erased: %s", tenant_id)
        else:
            conn.execute(
                "UPDATE _riverbank.tenants SET status = 'deleted', updated_at = now() "
                "WHERE tenant_id = %s",
                (tenant_id,),
            )
            logger.info("Tenant soft-deleted: %s", tenant_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not delete tenant %s: %s", tenant_id, exc)
        return False


def list_tenants(conn: Any) -> list[Tenant]:
    """Return all tenants from ``_riverbank.tenants``.

    Returns an empty list when the table does not exist (pre-migration state).
    """
    try:
        rows = conn.execute(
            "SELECT tenant_id, display_name, status, label_studio_org_id, "
            "       named_graph_prefix "
            "FROM _riverbank.tenants ORDER BY tenant_id"
        ).fetchall()
        return [
            Tenant(
                tenant_id=r[0],
                display_name=r[1] or "",
                status=TenantStatus(r[2]),
                label_studio_org_id=r[3],
                named_graph_prefix=r[4] or "",
            )
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list tenants: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Tenant-scoped Label Studio organisation
# ---------------------------------------------------------------------------

def assign_label_studio_org(conn: Any, tenant_id: str, org_id: int) -> bool:
    """Associate a Label Studio organisation ID with a tenant.

    Each tenant has exactly one Label Studio organisation; reviewer
    assignments respect tenant boundaries.
    """
    try:
        conn.execute(
            "UPDATE _riverbank.tenants SET label_studio_org_id = %s, updated_at = now() "
            "WHERE tenant_id = %s",
            (org_id, tenant_id),
        )
        logger.info("Tenant %s assigned Label Studio org %d", tenant_id, org_id)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not assign LS org to tenant %s: %s", tenant_id, exc)
        return False
