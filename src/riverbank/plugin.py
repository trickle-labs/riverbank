from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

_GROUPS: dict[str, str] = {
    "parsers": "riverbank.parsers",
    "fragmenters": "riverbank.fragmenters",
    "extractors": "riverbank.extractors",
    "connectors": "riverbank.connectors",
    "reviewers": "riverbank.reviewers",
}


def load_plugins(group: str) -> dict[str, Any]:
    """Load all plugins registered under the given extension-point group.

    Returns a dict mapping plugin name → plugin class.
    The package must be installed (``pip install -e .``) for entry points
    to be discoverable.

    Example::

        extractors = load_plugins("extractors")
        extractor = extractors["noop"]()
    """
    ep_group = _GROUPS.get(group, group)
    return {ep.name: ep.load() for ep in entry_points(group=ep_group)}
