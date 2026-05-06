"""SBOM generation and CVE audit for riverbank.

v0.10.0: CycloneDX SBOM output (JSON and XML) with pip-audit CVE scanning.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


OutputFormat = Literal["json", "xml"]


@dataclass
class SBOMResult:
    """Result of an SBOM generation run."""

    output_path: Path
    fmt: OutputFormat
    vulnerabilities: list[dict] = field(default_factory=list)

    @property
    def has_vulnerabilities(self) -> bool:
        return bool(self.vulnerabilities)

    @property
    def vulnerability_count(self) -> int:
        return len(self.vulnerabilities)


def generate_sbom(
    output_path: Path,
    fmt: OutputFormat = "json",
) -> SBOMResult:
    """Generate a CycloneDX SBOM for the installed riverbank package.

    Uses ``cyclonedx-py`` (the ``cyclonedx-bom`` package) to produce the SBOM.
    Falls back to a minimal hand-built CycloneDX document when ``cyclonedx-py``
    is not installed, so the command is always usable and only the ``[sbom]``
    extra is needed for production supply-chain workflows.

    Parameters
    ----------
    output_path:
        File path to write the SBOM to.
    fmt:
        Output format — ``"json"`` (default) or ``"xml"``.

    Returns
    -------
    SBOMResult
        Populated with the output path and format.  Vulnerability data is
        filled in separately by :func:`audit_vulnerabilities`.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Attempt to use cyclonedx-py (installed via the [sbom] extra or [dev])
    python = sys.executable
    try:
        result = subprocess.run(
            [
                python, "-m", "cyclonedx_py",
                "environment",
                "--output-format", fmt.upper(),
                "--outfile", str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return SBOMResult(output_path=output_path, fmt=fmt)
        # cyclonedx_py may use a different sub-command on older versions
        result2 = subprocess.run(
            [
                python, "-m", "cyclonedx_py",
                "pip",
                "--output-format", fmt.upper(),
                "--outfile", str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result2.returncode == 0:
            return SBOMResult(output_path=output_path, fmt=fmt)
    except FileNotFoundError:
        pass

    # Fallback: build a minimal CycloneDX JSON document ourselves
    _write_minimal_sbom(output_path, fmt)
    return SBOMResult(output_path=output_path, fmt=fmt)


def _write_minimal_sbom(output_path: Path, fmt: OutputFormat) -> None:
    """Write a minimal but valid CycloneDX 1.6 document as a fallback."""
    from riverbank import __version__  # noqa: PLC0415

    if fmt == "json":
        doc = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "metadata": {
                "component": {
                    "type": "library",
                    "name": "riverbank",
                    "version": __version__,
                }
            },
            "components": [],
        }
        output_path.write_text(json.dumps(doc, indent=2))
    else:
        # Minimal XML
        from riverbank import __version__ as _v  # noqa: PLC0415

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<bom xmlns="http://cyclonedx.org/schema/bom/1.6" version="1">\n'
            "  <metadata>\n"
            "    <component type=\"library\">\n"
            f"      <name>riverbank</name>\n"
            f"      <version>{_v}</version>\n"
            "    </component>\n"
            "  </metadata>\n"
            "  <components/>\n"
            "</bom>\n"
        )
        output_path.write_text(xml)


def audit_vulnerabilities() -> list[dict]:
    """Run pip-audit and return a list of vulnerability dicts.

    Each dict has keys: ``name``, ``version``, ``id``, ``fix_versions``.

    Returns an empty list when pip-audit is not installed or reports no issues.
    """
    python = sys.executable
    try:
        result = subprocess.run(
            [python, "-m", "pip_audit", "--format", "json", "--output", "-"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []

    if result.returncode == 0:
        # No vulnerabilities
        return []

    # pip-audit exits non-zero when it finds vulnerabilities
    # Try to parse JSON output
    raw = result.stdout.strip()
    if not raw:
        raw = result.stderr.strip()
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    vulns: list[dict] = []
    # pip-audit JSON format: {"dependencies": [{"name": ..., "version": ..., "vulns": [...]}]}
    deps = data if isinstance(data, list) else data.get("dependencies", data.get("results", []))
    for dep in deps:
        dep_vulns = dep.get("vulns", dep.get("vulnerabilities", []))
        if dep_vulns:
            for v in dep_vulns:
                vulns.append(
                    {
                        "name": dep.get("name", ""),
                        "version": dep.get("version", ""),
                        "id": v.get("id", v.get("vuln_id", "")),
                        "fix_versions": v.get("fix_versions", []),
                    }
                )
    return vulns
