"""Unit tests for Helm chart structure (v0.7.0)."""
from __future__ import annotations

from pathlib import Path

import yaml

HELM_ROOT = Path(__file__).parent.parent.parent / "helm" / "riverbank"


def test_helm_chart_yaml_exists() -> None:
    """helm/riverbank/Chart.yaml must exist."""
    assert (HELM_ROOT / "Chart.yaml").exists()


def test_helm_chart_yaml_is_valid() -> None:
    """Chart.yaml must be valid YAML with required fields."""
    chart = yaml.safe_load((HELM_ROOT / "Chart.yaml").read_text())
    assert chart["apiVersion"] == "v2"
    assert chart["name"] == "riverbank"
    assert "version" in chart
    assert "appVersion" in chart


def test_helm_values_yaml_exists() -> None:
    """helm/riverbank/values.yaml must exist."""
    assert (HELM_ROOT / "values.yaml").exists()


def test_helm_values_yaml_is_valid() -> None:
    """values.yaml must be valid YAML."""
    values = yaml.safe_load((HELM_ROOT / "values.yaml").read_text())
    assert isinstance(values, dict)


def test_helm_values_replica_count_is_at_least_1() -> None:
    """replicaCount must be >= 1 (multi-replica worker support)."""
    values = yaml.safe_load((HELM_ROOT / "values.yaml").read_text())
    assert values["replicaCount"] >= 1


def test_helm_values_metrics_enabled() -> None:
    """Prometheus metrics must be enabled by default."""
    values = yaml.safe_load((HELM_ROOT / "values.yaml").read_text())
    assert values["metrics"]["enabled"] is True


def test_helm_values_metrics_has_path() -> None:
    """metrics.path must be '/metrics'."""
    values = yaml.safe_load((HELM_ROOT / "values.yaml").read_text())
    assert values["metrics"]["path"] == "/metrics"


def test_helm_values_circuit_breakers_configured() -> None:
    """circuitBreakers section must exist with at least openai config."""
    values = yaml.safe_load((HELM_ROOT / "values.yaml").read_text())
    cb = values.get("circuitBreakers", {})
    assert "openai" in cb
    assert "failMax" in cb["openai"]
    assert "maxConcurrency" in cb["openai"]


def test_helm_values_secret_management_configured() -> None:
    """secrets section must exist with existingSecret and vault sub-sections."""
    values = yaml.safe_load((HELM_ROOT / "values.yaml").read_text())
    assert "secrets" in values
    assert "existingSecret" in values["secrets"]
    assert "vault" in values["secrets"]


def test_helm_deployment_template_exists() -> None:
    """templates/deployment.yaml must exist."""
    assert (HELM_ROOT / "templates" / "deployment.yaml").exists()


def test_helm_helpers_tpl_exists() -> None:
    """templates/_helpers.tpl must exist."""
    assert (HELM_ROOT / "templates" / "_helpers.tpl").exists()


def test_helm_configmap_template_exists() -> None:
    """templates/configmap.yaml must exist."""
    assert (HELM_ROOT / "templates" / "configmap.yaml").exists()


def test_helm_chart_version_matches_app_version() -> None:
    """Chart version and appVersion should match the riverbank package version."""
    from riverbank import __version__

    chart = yaml.safe_load((HELM_ROOT / "Chart.yaml").read_text())
    # appVersion should start with or equal the package version
    assert chart["appVersion"].startswith(__version__)


def test_helm_values_has_otel_endpoint_config() -> None:
    """riverbank.otelExporterOtlpEndpoint must exist in values (can be empty string)."""
    values = yaml.safe_load((HELM_ROOT / "values.yaml").read_text())
    assert "otelExporterOtlpEndpoint" in values.get("riverbank", {})


def test_perses_dashboard_exists() -> None:
    """perses/riverbank-overview.json must exist."""
    perses_file = Path(__file__).parent.parent.parent / "perses" / "riverbank-overview.json"
    assert perses_file.exists()


def test_perses_dashboard_is_valid_json() -> None:
    """perses/riverbank-overview.json must be valid JSON with expected structure."""
    import json

    perses_file = Path(__file__).parent.parent.parent / "perses" / "riverbank-overview.json"
    dashboard = json.loads(perses_file.read_text())
    assert dashboard["kind"] == "Dashboard"
    assert "spec" in dashboard
    assert "panels" in dashboard["spec"]


def test_perses_dashboard_has_cost_panels() -> None:
    """Perses dashboard must include cost panels for cost-per-source/-profile/trend/monthly."""
    import json

    perses_file = Path(__file__).parent.parent.parent / "perses" / "riverbank-overview.json"
    dashboard = json.loads(perses_file.read_text())
    panels = dashboard["spec"]["panels"]

    # Check for cost-related panels
    cost_panel_keys = [k for k in panels if "cost" in k.lower()]
    assert len(cost_panel_keys) >= 2, (
        f"Expected at least 2 cost panels, found {cost_panel_keys}"
    )


def test_perses_dashboard_has_shacl_panel() -> None:
    """Perses dashboard must include a SHACL quality score panel."""
    import json

    perses_file = Path(__file__).parent.parent.parent / "perses" / "riverbank-overview.json"
    dashboard = json.loads(perses_file.read_text())
    panels = dashboard["spec"]["panels"]
    assert any("shacl" in k.lower() for k in panels)


def test_perses_dashboard_has_circuit_breaker_panel() -> None:
    """Perses dashboard must include a circuit breaker panel."""
    import json

    perses_file = Path(__file__).parent.parent.parent / "perses" / "riverbank-overview.json"
    dashboard = json.loads(perses_file.read_text())
    panels = dashboard["spec"]["panels"]
    assert any("circuit" in k.lower() for k in panels)
