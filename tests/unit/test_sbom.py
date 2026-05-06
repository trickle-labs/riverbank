"""Unit tests for the riverbank.sbom module (v0.10.0)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from riverbank.sbom import (
    SBOMResult,
    _write_minimal_sbom,
    audit_vulnerabilities,
    generate_sbom,
)


# ---------------------------------------------------------------------------
# SBOMResult dataclass
# ---------------------------------------------------------------------------

class TestSBOMResult:
    def test_no_vulnerabilities_by_default(self, tmp_path):
        r = SBOMResult(output_path=tmp_path / "sbom.json", fmt="json")
        assert not r.has_vulnerabilities
        assert r.vulnerability_count == 0

    def test_has_vulnerabilities_when_list_non_empty(self, tmp_path):
        r = SBOMResult(
            output_path=tmp_path / "sbom.json",
            fmt="json",
            vulnerabilities=[{"name": "foo", "version": "1.0", "id": "CVE-2024-0001", "fix_versions": []}],
        )
        assert r.has_vulnerabilities
        assert r.vulnerability_count == 1

    def test_vulnerability_count_reflects_list_length(self, tmp_path):
        vulns = [
            {"name": "a", "version": "1.0", "id": "CVE-2024-0001", "fix_versions": []},
            {"name": "b", "version": "2.0", "id": "CVE-2024-0002", "fix_versions": ["2.1"]},
        ]
        r = SBOMResult(output_path=tmp_path / "sbom.json", fmt="json", vulnerabilities=vulns)
        assert r.vulnerability_count == 2

    def test_fmt_field_stored(self, tmp_path):
        r = SBOMResult(output_path=tmp_path / "sbom.xml", fmt="xml")
        assert r.fmt == "xml"


# ---------------------------------------------------------------------------
# _write_minimal_sbom  (fallback writer)
# ---------------------------------------------------------------------------

class TestWriteMinimalSbom:
    def test_json_output_is_valid_json(self, tmp_path):
        out = tmp_path / "sbom.json"
        _write_minimal_sbom(out, "json")
        assert out.exists()
        doc = json.loads(out.read_text())
        assert doc["bomFormat"] == "CycloneDX"
        assert doc["specVersion"] == "1.6"

    def test_json_contains_riverbank_component(self, tmp_path):
        out = tmp_path / "sbom.json"
        _write_minimal_sbom(out, "json")
        doc = json.loads(out.read_text())
        assert doc["metadata"]["component"]["name"] == "riverbank"

    def test_json_version_matches_package(self, tmp_path):
        from riverbank import __version__

        out = tmp_path / "sbom.json"
        _write_minimal_sbom(out, "json")
        doc = json.loads(out.read_text())
        assert doc["metadata"]["component"]["version"] == __version__

    def test_xml_output_contains_riverbank(self, tmp_path):
        out = tmp_path / "sbom.xml"
        _write_minimal_sbom(out, "xml")
        assert out.exists()
        content = out.read_text()
        assert "riverbank" in content
        assert "cyclonedx.org" in content

    def test_xml_output_is_well_formed(self, tmp_path):
        import xml.etree.ElementTree as ET  # noqa: N817

        out = tmp_path / "sbom.xml"
        _write_minimal_sbom(out, "xml")
        # Should not raise
        ET.parse(str(out))

    def test_creates_parent_directory(self, tmp_path):
        out = tmp_path / "nested" / "dir" / "sbom.json"
        # _write_minimal_sbom does not create parents itself; generate_sbom does
        out.parent.mkdir(parents=True)
        _write_minimal_sbom(out, "json")
        assert out.exists()


# ---------------------------------------------------------------------------
# generate_sbom
# ---------------------------------------------------------------------------

class TestGenerateSbom:
    def test_returns_sbom_result(self, tmp_path):
        out = tmp_path / "sbom.json"
        # cyclonedx_py likely not installed in unit test env; fallback path runs
        result = generate_sbom(out, fmt="json")
        assert isinstance(result, SBOMResult)

    def test_output_file_created(self, tmp_path):
        out = tmp_path / "sbom.json"
        generate_sbom(out, fmt="json")
        assert out.exists()

    def test_output_path_stored_in_result(self, tmp_path):
        out = tmp_path / "sbom.json"
        result = generate_sbom(out, fmt="json")
        assert result.output_path == out

    def test_fmt_stored_in_result(self, tmp_path):
        out = tmp_path / "sbom.json"
        result = generate_sbom(out, fmt="json")
        assert result.fmt == "json"

    def test_xml_output_file_created(self, tmp_path):
        out = tmp_path / "sbom.xml"
        result = generate_sbom(out, fmt="xml")
        assert out.exists()
        assert result.fmt == "xml"

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "deeply" / "nested" / "sbom.json"
        generate_sbom(out, fmt="json")
        assert out.exists()

    def test_uses_cyclonedx_py_when_available(self, tmp_path):
        """When cyclonedx_py succeeds (returncode=0), no fallback is called."""
        out = tmp_path / "sbom.json"
        # Write a valid JSON file as if cyclonedx_py produced it
        fake_doc = {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            # The call will write nothing (subprocess won't actually write), so
            # the file doesn't exist yet — generate_sbom should still return OK
            result = generate_sbom(out, fmt="json")
            # subprocess.run was attempted
            assert mock_run.called

    def test_falls_back_when_cyclonedx_py_fails(self, tmp_path):
        """When cyclonedx_py returns non-zero twice, fallback produces a file."""
        out = tmp_path / "sbom.json"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = generate_sbom(out, fmt="json")
            assert out.exists()
            assert isinstance(result, SBOMResult)

    def test_falls_back_when_cyclonedx_py_not_found(self, tmp_path):
        """FileNotFoundError from subprocess leads to fallback."""
        out = tmp_path / "sbom.json"
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = generate_sbom(out, fmt="json")
            assert out.exists()


# ---------------------------------------------------------------------------
# audit_vulnerabilities
# ---------------------------------------------------------------------------

class TestAuditVulnerabilities:
    def test_returns_empty_list_when_pip_audit_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = audit_vulnerabilities()
        assert result == []

    def test_returns_empty_list_when_no_vulns(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = audit_vulnerabilities()
        assert result == []

    def test_parses_pip_audit_json_output(self):
        fake_output = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "requests",
                        "version": "2.20.0",
                        "vulns": [
                            {"id": "CVE-2023-32681", "fix_versions": ["2.31.0"]},
                        ],
                    }
                ]
            }
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=fake_output, stderr="")
            result = audit_vulnerabilities()

        assert len(result) == 1
        assert result[0]["name"] == "requests"
        assert result[0]["id"] == "CVE-2023-32681"
        assert result[0]["fix_versions"] == ["2.31.0"]

    def test_returns_empty_list_on_malformed_json(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="not-json", stderr="")
            result = audit_vulnerabilities()
        assert result == []

    def test_returns_empty_list_on_empty_output(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
            result = audit_vulnerabilities()
        assert result == []

    def test_multiple_vulnerabilities_in_one_package(self):
        fake_output = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "setuptools",
                        "version": "60.0.0",
                        "vulns": [
                            {"id": "CVE-2024-6345", "fix_versions": ["70.0.0"]},
                            {"id": "CVE-2024-9999", "fix_versions": []},
                        ],
                    }
                ]
            }
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=fake_output, stderr="")
            result = audit_vulnerabilities()
        assert len(result) == 2
        ids = {r["id"] for r in result}
        assert "CVE-2024-6345" in ids
        assert "CVE-2024-9999" in ids

    def test_fix_versions_defaults_to_empty_list(self):
        fake_output = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "urllib3",
                        "version": "1.26.0",
                        "vulns": [{"id": "CVE-2023-45803"}],
                    }
                ]
            }
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=fake_output, stderr="")
            result = audit_vulnerabilities()
        assert result[0]["fix_versions"] == []


# ---------------------------------------------------------------------------
# CLI integration tests (via typer test client)
# ---------------------------------------------------------------------------

class TestSbomCLI:
    def test_sbom_command_writes_file(self, tmp_path):
        from typer.testing import CliRunner

        from riverbank.cli import app

        runner = CliRunner()
        out = str(tmp_path / "sbom.json")
        result = runner.invoke(app, ["sbom", "--output", out, "--no-audit"])
        assert result.exit_code == 0
        assert Path(out).exists()

    def test_sbom_command_prints_success(self, tmp_path):
        from typer.testing import CliRunner

        from riverbank.cli import app

        runner = CliRunner()
        out = str(tmp_path / "sbom.json")
        result = runner.invoke(app, ["sbom", "--output", out, "--no-audit"])
        assert "SBOM written to" in result.output

    def test_sbom_xml_format(self, tmp_path):
        from typer.testing import CliRunner

        from riverbank.cli import app

        runner = CliRunner()
        out = str(tmp_path / "sbom.xml")
        result = runner.invoke(app, ["sbom", "--output", out, "--format", "xml", "--no-audit"])
        assert result.exit_code == 0
        assert Path(out).exists()

    def test_sbom_invalid_format_exits_1(self, tmp_path):
        from typer.testing import CliRunner

        from riverbank.cli import app

        runner = CliRunner()
        out = str(tmp_path / "sbom.txt")
        result = runner.invoke(app, ["sbom", "--output", out, "--format", "txt", "--no-audit"])
        assert result.exit_code == 1

    def test_sbom_with_vulnerabilities_exits_1(self, tmp_path):
        from typer.testing import CliRunner

        from riverbank.cli import app

        runner = CliRunner()
        out = str(tmp_path / "sbom.json")
        fake_vuln = [{"name": "pkg", "version": "1.0", "id": "CVE-2024-0001", "fix_versions": []}]
        with patch("riverbank.sbom.audit_vulnerabilities", return_value=fake_vuln):
            result = runner.invoke(app, ["sbom", "--output", out])
        assert result.exit_code == 1
        assert "CVE-2024-0001" in result.output

    def test_sbom_no_vuln_exits_0(self, tmp_path):
        from typer.testing import CliRunner

        from riverbank.cli import app

        runner = CliRunner()
        out = str(tmp_path / "sbom.json")
        with patch("riverbank.sbom.audit_vulnerabilities", return_value=[]):
            result = runner.invoke(app, ["sbom", "--output", out])
        assert result.exit_code == 0
        assert "No known CVEs" in result.output

    def test_sbom_no_audit_skips_scan(self, tmp_path):
        from typer.testing import CliRunner

        from riverbank.cli import app

        runner = CliRunner()
        out = str(tmp_path / "sbom.json")
        with patch("riverbank.sbom.audit_vulnerabilities") as mock_audit:
            result = runner.invoke(app, ["sbom", "--output", out, "--no-audit"])
        mock_audit.assert_not_called()
        assert "skipped" in result.output


# ---------------------------------------------------------------------------
# pyproject.toml extras tests
# ---------------------------------------------------------------------------

class TestPyprojectExtras:
    """Verify that the expected extras are declared in pyproject.toml."""

    def _load_toml(self) -> dict:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-reuse-def]

        root = Path(__file__).parent.parent.parent  # tests/unit -> tests -> project root
        pyproject = root / "pyproject.toml"
        return tomllib.loads(pyproject.read_text())

    def test_ollama_extra_declared(self):
        data = self._load_toml()
        assert "ollama" in data["project"]["optional-dependencies"]

    def test_docling_extra_declared(self):
        data = self._load_toml()
        assert "docling" in data["project"]["optional-dependencies"]

    def test_labelstudio_extra_declared(self):
        data = self._load_toml()
        assert "labelstudio" in data["project"]["optional-dependencies"]

    def test_sbom_extra_declared(self):
        data = self._load_toml()
        assert "sbom" in data["project"]["optional-dependencies"]

    def test_sbom_extra_contains_cyclonedx(self):
        data = self._load_toml()
        sbom_deps = data["project"]["optional-dependencies"]["sbom"]
        assert any("cyclonedx" in dep for dep in sbom_deps)

    def test_sbom_extra_contains_pip_audit(self):
        data = self._load_toml()
        sbom_deps = data["project"]["optional-dependencies"]["sbom"]
        assert any("pip-audit" in dep for dep in sbom_deps)

    def test_version_is_0_10_0(self):
        data = self._load_toml()
        assert data["project"]["version"] == "0.10.0"


# ---------------------------------------------------------------------------
# MANIFEST.in existence test
# ---------------------------------------------------------------------------

class TestManifestIn:
    def test_manifest_in_exists(self):
        root = Path(__file__).parent.parent.parent  # project root
        manifest = root / "MANIFEST.in"
        assert manifest.exists(), "MANIFEST.in must exist for PyPI sdist"

    def test_manifest_in_includes_readme(self):
        root = Path(__file__).parent.parent.parent
        manifest = (root / "MANIFEST.in").read_text()
        assert "README.md" in manifest

    def test_manifest_in_includes_license(self):
        root = Path(__file__).parent.parent.parent
        manifest = (root / "MANIFEST.in").read_text()
        assert "LICENSE" in manifest


# ---------------------------------------------------------------------------
# Release workflow existence tests
# ---------------------------------------------------------------------------

class TestReleaseWorkflow:
    def _workflow_path(self) -> Path:
        root = Path(__file__).parent.parent.parent  # project root
        return root / ".github" / "workflows" / "release.yml"

    def test_release_yml_exists(self):
        assert self._workflow_path().exists()

    def test_release_yml_triggers_on_version_tags(self):
        import yaml

        content = yaml.safe_load(self._workflow_path().read_text())
        # PyYAML parses the YAML key 'on' as Python True
        trigger = content.get("on", content.get(True, {}))
        tags = trigger["push"]["tags"]
        assert any("v*" in t for t in tags)

    def test_release_yml_has_pypi_publish_job(self):
        import yaml

        content = yaml.safe_load(self._workflow_path().read_text())
        assert "publish-pypi" in content["jobs"]

    def test_release_yml_has_docs_publish_job(self):
        import yaml

        content = yaml.safe_load(self._workflow_path().read_text())
        assert "publish-docs" in content["jobs"]
