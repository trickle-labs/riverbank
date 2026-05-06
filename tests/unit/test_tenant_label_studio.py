"""Unit tests for tenant-scoped Label Studio organisation (v0.9.0)."""
from __future__ import annotations

import unittest.mock as mock


def test_tenant_has_label_studio_org_id_field() -> None:
    """Tenant dataclass has a label_studio_org_id field."""
    from riverbank.tenants import Tenant

    t = Tenant(tenant_id="acme", label_studio_org_id=99)
    assert t.label_studio_org_id == 99


def test_tenant_label_studio_org_id_defaults_to_none() -> None:
    """Tenant.label_studio_org_id defaults to None."""
    from riverbank.tenants import Tenant

    t = Tenant(tenant_id="acme")
    assert t.label_studio_org_id is None


def test_assign_label_studio_org_success() -> None:
    """assign_label_studio_org returns True on successful update."""
    from riverbank.tenants import assign_label_studio_org

    conn = mock.MagicMock()
    result = assign_label_studio_org(conn, "acme", 7)

    assert result is True


def test_assign_label_studio_org_passes_org_id() -> None:
    """assign_label_studio_org passes org_id and tenant_id to the DB call."""
    from riverbank.tenants import assign_label_studio_org

    conn = mock.MagicMock()
    assign_label_studio_org(conn, "my-tenant", 123)

    call = conn.execute.call_args
    sql = call[0][0]
    params = call[0][1]
    assert "label_studio_org_id" in sql
    assert 123 in params
    assert "my-tenant" in params


def test_assign_label_studio_org_returns_false_on_error() -> None:
    """assign_label_studio_org returns False when DB update fails."""
    from riverbank.tenants import assign_label_studio_org

    conn = mock.MagicMock()
    conn.execute.side_effect = Exception("relation not found")

    result = assign_label_studio_org(conn, "acme", 5)
    assert result is False


def test_create_tenant_with_ls_org_persists_org_id() -> None:
    """create_tenant includes label_studio_org_id in the insert payload."""
    from riverbank.tenants import Tenant, create_tenant

    conn = mock.MagicMock()
    tenant = Tenant(tenant_id="widget-co", label_studio_org_id=55)
    create_tenant(conn, tenant)

    # The INSERT call should include the org_id in its params
    insert_call = conn.execute.call_args_list[1]  # second call is INSERT
    params = insert_call[0][1]
    assert 55 in params


def test_two_tenants_have_independent_org_ids() -> None:
    """Two tenants with different org_ids remain independent."""
    from riverbank.tenants import Tenant

    t1 = Tenant(tenant_id="org-a", label_studio_org_id=10)
    t2 = Tenant(tenant_id="org-b", label_studio_org_id=20)

    assert t1.label_studio_org_id != t2.label_studio_org_id
    assert t1.tenant_id != t2.tenant_id


def test_tenant_named_graph_scoped_to_tenant() -> None:
    """Each tenant has its own named graph prefix scoped to its tenant_id."""
    from riverbank.tenants import Tenant

    t1 = Tenant(tenant_id="alpha")
    t2 = Tenant(tenant_id="beta")

    assert t1.named_graph_prefix != t2.named_graph_prefix
    assert "alpha" in t1.named_graph_prefix
    assert "beta" in t2.named_graph_prefix
    # Ensure no cross-contamination
    assert "beta" not in t1.named_graph_prefix
    assert "alpha" not in t2.named_graph_prefix
