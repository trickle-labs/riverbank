# Generate an SBOM

Produce a Software Bill of Materials listing all dependencies.

## Using pip

```bash
pip install pip-licenses
pip-licenses --format=json --output-file=sbom.json
```

## Using syft (CycloneDX)

```bash
syft dir:. -o cyclonedx-json > sbom.cyclonedx.json
```

## Using the Docker image

```bash
syft ghcr.io/trickle-labs/riverbank:latest -o spdx-json > sbom.spdx.json
```

## What's included

The SBOM covers:

- All Python runtime dependencies (from `pyproject.toml`)
- Optional extras groups (`[ingest]`, `[hardening]`, `[review]`, etc.)
- System libraries in the Docker image
- PostgreSQL extension versions (pg-ripple, pg-trickle, pg-tide)

## CI integration

Add to your CI workflow:

```yaml
- name: Generate SBOM
  run: syft dir:. -o cyclonedx-json > sbom.cyclonedx.json
- uses: actions/upload-artifact@v4
  with:
    name: sbom
    path: sbom.cyclonedx.json
```
