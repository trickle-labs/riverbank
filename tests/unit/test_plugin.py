from __future__ import annotations


def test_load_extractors_includes_noop() -> None:
    """Verify the no-op extractor is registered via entry-points.

    Requires the package to be installed (``pip install -e .``) so that
    entry-point metadata is discoverable by importlib.
    """
    from riverbank.plugin import load_plugins

    plugins = load_plugins("extractors")
    assert "noop" in plugins
    extractor_cls = plugins["noop"]
    assert extractor_cls.name == "noop"


def test_load_parsers_includes_markdown() -> None:
    from riverbank.plugin import load_plugins

    plugins = load_plugins("parsers")
    assert "markdown" in plugins


def test_load_parsers_includes_docling() -> None:
    """Docling parser must be registered as a riverbank.parsers entry point."""
    from riverbank.plugin import load_plugins

    plugins = load_plugins("parsers")
    assert "docling" in plugins
    parser_cls = plugins["docling"]
    assert parser_cls.name == "docling"


def test_load_connectors_includes_filesystem() -> None:
    from riverbank.plugin import load_plugins

    plugins = load_plugins("connectors")
    assert "filesystem" in plugins
