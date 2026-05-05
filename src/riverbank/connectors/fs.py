from __future__ import annotations

from typing import ClassVar, Iterator


class FilesystemConnector:
    """Filesystem document connector.

    Discovers documents by walking a directory tree and yields SourceRecord
    objects for each matching file.  Full implementation arrives in v0.2.0.
    """

    name: ClassVar[str] = "filesystem"

    def discover(self, config: dict) -> Iterator[object]:
        raise NotImplementedError("FilesystemConnector not yet implemented — arriving in v0.2.0")
        yield  # type: ignore[misc]

    def fetch(self, source: object) -> bytes:
        raise NotImplementedError("FilesystemConnector not yet implemented — arriving in v0.2.0")
