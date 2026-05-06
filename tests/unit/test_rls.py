"""Unit tests for multi-tenant RLS activation (v0.9.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_tenant_status_enum_values() -> None:
    """TenantStatus has exactly 3 values: active, suspended, deleted."""
    from riverbank.tenants import TenantStatus

    statuses = {s.value for s in TenantStatus}
    assert statuses == {"active", "suspended", "deleted"}


def test_tenant_dataclass_defaults() -> None:
    """Tenant has sensible defaults for all optional fields."""
    from riverbank.tenants import Tenant, TenantStatus

    t = Tenant(tenant_id="acme")
    assert t.display_name == ""
    assert t.status == TenantStatus.ACTIVE
    assert t.label_studio_org_id is None
    assert "acme" in t.named_graph_prefix


def test_tenant_named_graph_prefix_auto_populated() -> None:
    """Tenant.named_graph_prefix is auto-populated from tenant_id."""
    from riverbank.tenants import Tenant

    t = Tenant(tenant_id="my-org")
    assert t.named_graph_prefix == "http://riverbank.example/tenant/my-org/graph/"


def test_tenant_named_graph_prefix_explicit() -> None:
    """Tenant.named_graph_prefix is preserved when explicitly set."""
    from riverbank.tenants import Tenant

    t = Tenant(tenant_id="my-org", named_graph_prefix="http://custom.example/graphs/")
    assert t.named_graph_prefix == "http://custom.example/graphs/"


def test_rls_tables_list_contains_all_catalog_tables() -> None:
    """_RLS_TABLES contains all six _riverbank catalog tables."""
    from riverbank.tenants import _RLS_TABLES

    assert set(_RLS_TABLES) == {"sources", "fragments", "profiles", "runs", "artifact_deps", "log"}


def test_enable_rls_calls_alter_table() -> None:
    """enable_rls executes ALTER TABLE … ENABLE ROW LEVEL SECURITY."""
    from riverbank.tenants import enable_rls

    conn = mock.MagicMock()
    result = enable_rls(conn, "sources")

    assert result is True
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "sources" in sql


def test_enable_rls_returns_false_on_error() -> None:
    """enable_rls returns False when the ALTER TABLE fails."""
    from riverbank.tenants import enable_rls

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("permission denied")

    result = enable_rls(conn, "sources")
    assert result is False


def test_create_rls_policy_calls_create_policy() -> None:
    """create_rls_policy issues DROP POLICY + CREATE POLICY."""
    from riverbank.tenants import create_rls_policy

    conn = mock.MagicMock()
    result = create_rls_policy(conn, "fragments")

    assert result is True
    assert conn.execute.call_count == 2
    calls = [c[0][0] for c in conn.execute.call_args_list]
    assert any("DROP POLICY" in c for c in calls)
    assert any("CREATE POLICY" in c for c in calls)


def test_create_rls_policy_uses_current_setting_guc() -> None:
    """create_rls_policy uses app.current_tenant_id GUC in USING clause."""
    from riverbank.tenants import create_rls_policy

    conn = mock.MagicMock()
    create_rls_policy(conn, "runs")

    calls = [c[0][0] for c in conn.execute.call_args_list]
    policy_sql = next(c for c in calls if "CREATE POLICY" in c)
    assert "app.current_tenant_id" in policy_sql


def test_activate_rls_for_all_tables_covers_all_tables() -> None:
    """activate_rls_for_all_tables calls enable_rls and create_rls_policy for every table."""
    from riverbank.tenants import _RLS_TABLES, activate_rls_for_all_tables

    conn = mock.MagicMock()
    results = activate_rls_for_all_tables(conn)

    assert set(results.keys()) == set(_RLS_TABLES)


def test_activate_rls_all_succeed() -> None:
    """activate_rls_for_all_tables returns all True when DB calls succeed."""
    from riverbank.tenants import activate_rls_for_all_tables

    conn = mock.MagicMock()
    results = activate_rls_for_all_tables(conn)

    assert all(results.values())


def test_set_current_tenant_executes_set_guc() -> None:
    """set_current_tenant executes SET app.current_tenant_id."""
    from riverbank.tenants import set_current_tenant

    conn = mock.MagicMock()
    set_current_tenant(conn, "acme")

    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "app.current_tenant_id" in sql
    assert "acme" in sql


def test_set_current_tenant_rejects_invalid_id() -> None:
    """set_current_tenant raises ValueError for invalid tenant_id characters."""
    from riverbank.tenants import set_current_tenant

    conn = mock.MagicMock()
    try:
        set_current_tenant(conn, "acme'; DROP TABLE users; --")
        assert False, "Expected ValueError"  # noqa: PT015
    except ValueError:
        pass

    conn.execute.assert_not_called()


def test_clear_current_tenant_resets_guc() -> None:
    """clear_current_tenant executes RESET app.current_tenant_id."""
    from riverbank.tenants import clear_current_tenant

    conn = mock.MagicMock()
    clear_current_tenant(conn)

    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "RESET" in sql
    assert "app.current_tenant_id" in sql


def test_create_tenant_persists_row() -> None:
    """create_tenant calls conn.execute to insert/upsert a tenant row."""
    from riverbank.tenants import Tenant, create_tenant

    conn = mock.MagicMock()
    tenant = Tenant(tenant_id="acme", display_name="Acme Corp")
    result = create_tenant(conn, tenant)

    assert result is True
    assert conn.execute.call_count == 2  # CREATE TABLE IF NOT EXISTS + INSERT


def test_create_tenant_returns_false_on_error() -> None:
    """create_tenant returns False when the DB operation fails."""
    from riverbank.tenants import Tenant, create_tenant

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("connection refused")
    tenant = Tenant(tenant_id="acme")

    result = create_tenant(conn, tenant)
    assert result is False


def test_suspend_tenant_updates_status() -> None:
    """suspend_tenant issues an UPDATE SET status='suspended'."""
    from riverbank.tenants import suspend_tenant

    conn = mock.MagicMock()
    result = suspend_tenant(conn, "acme")

    assert result is True
    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "suspended" in sql


def test_delete_tenant_soft_delete() -> None:
    """delete_tenant with gdpr_erasure=False marks status='deleted'."""
    from riverbank.tenants import delete_tenant

    conn = mock.MagicMock()
    result = delete_tenant(conn, "acme", gdpr_erasure=False)

    assert result is True
    sql = conn.execute.call_args[0][0]
    assert "deleted" in sql


def test_delete_tenant_gdpr_erasure_deletes_data_rows() -> None:
    """delete_tenant with gdpr_erasure=True deletes rows from all tables plus tenant record."""
    from riverbank.tenants import _RLS_TABLES, delete_tenant

    conn = mock.MagicMock()
    result = delete_tenant(conn, "acme", gdpr_erasure=True)

    assert result is True
    # Should call DELETE for each table + DELETE from tenants = len(_RLS_TABLES) + 1
    assert conn.execute.call_count == len(_RLS_TABLES) + 1


def test_assign_label_studio_org_updates_tenant() -> None:
    """assign_label_studio_org issues UPDATE with correct org_id."""
    from riverbank.tenants import assign_label_studio_org

    conn = mock.MagicMock()
    result = assign_label_studio_org(conn, "acme", 42)

    assert result is True
    conn.execute.assert_called_once()
    call = conn.execute.call_args
    assert 42 in call[0][1]


def test_list_tenants_returns_empty_on_error() -> None:
    """list_tenants returns empty list when table does not exist."""
    from riverbank.tenants import list_tenants

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("relation does not exist")

    result = list_tenants(conn)
    assert result == []


def test_list_tenants_returns_tenant_objects() -> None:
    """list_tenants converts DB rows to Tenant objects."""
    from riverbank.tenants import Tenant, TenantStatus, list_tenants

    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        ("acme", "Acme Corp", "active", 42, "http://riverbank.example/tenant/acme/graph/"),
        ("beta", "Beta LLC", "suspended", None, "http://riverbank.example/tenant/beta/graph/"),
    ]

    tenants = list_tenants(conn)
    assert len(tenants) == 2
    assert tenants[0].tenant_id == "acme"
    assert tenants[0].status == TenantStatus.ACTIVE
    assert tenants[0].label_studio_org_id == 42
    assert tenants[1].tenant_id == "beta"
    assert tenants[1].status == TenantStatus.SUSPENDED
