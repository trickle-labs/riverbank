from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterator

import xxhash

# Maps file extensions to MIME types
_MIME_MAP: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".rst": "text/x-rst",
}


@dataclass
class SourceRecord:
    """A single discoverable source document from the filesystem."""

    iri: str         # file:// URI
    path: Path
    content: bytes
    content_hash: bytes  # xxh3_128 digest
    mime_type: str = "text/markdown"


class FilesystemConnector:
    """Discovers documents by walking a directory tree.

    ``discover()`` yields one ``SourceRecord`` per matching file.
    ``watch()`` enters a continuous loop yielding records for modified files
    (requires ``watchdog`` — install with ``pip install riverbank[ingest]``).
    """

    name: ClassVar[str] = "filesystem"

    def discover(self, config: dict) -> Iterator[SourceRecord]:
        """Walk ``config["path"]`` and yield a ``SourceRecord`` per matching file.

        ``config`` keys:
        - ``path``: str or Path — root directory to walk
        - ``patterns``: list[str] — glob patterns (default ``["**/*.md"]``)
        """
        root = Path(config["path"])
        patterns: list[str] = config.get("patterns", ["**/*.md", "**/*.markdown"])

        seen: set[Path] = set()
        for pattern in patterns:
            for p in sorted(root.glob(pattern)):
                if not p.is_file() or p in seen:
                    continue
                seen.add(p)
                content = p.read_bytes()
                content_hash = xxhash.xxh3_128(content).digest()
                mime_type = _MIME_MAP.get(p.suffix.lower(), "application/octet-stream")
                yield SourceRecord(
                    iri=p.as_uri(),
                    path=p,
                    content=content,
                    content_hash=content_hash,
                    mime_type=mime_type,
                )

    def fetch(self, source: SourceRecord) -> bytes:
        """Read and return the current bytes for the given ``SourceRecord``."""
        return source.path.read_bytes()

    def watch(self, config: dict) -> Iterator[SourceRecord]:
        """Watch ``config["path"]`` for changes and yield modified ``SourceRecord``s.

        Requires the ``watchdog`` package::

            pip install riverbank[ingest]

        This method blocks indefinitely; send a keyboard interrupt to stop.
        """
        try:
            from watchdog.events import FileSystemEventHandler  # noqa: PLC0415
            from watchdog.observers import Observer  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "watchdog is required for directory-watcher mode. "
                "Install with: pip install 'riverbank[ingest]'"
            ) from exc

        import queue  # noqa: PLC0415

        root = Path(config["path"])
        patterns: list[str] = config.get("patterns", ["**/*.md", "**/*.markdown"])
        event_queue: queue.Queue[Path] = queue.Queue()

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):  # type: ignore[override]
                if not event.is_directory:
                    event_queue.put(Path(str(event.src_path)))

            def on_created(self, event):  # type: ignore[override]
                if not event.is_directory:
                    event_queue.put(Path(str(event.src_path)))

        observer = Observer()
        observer.schedule(_Handler(), str(root), recursive=True)
        observer.start()
        try:
            while True:
                try:
                    changed: Path = event_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                try:
                    rel = changed.relative_to(root)
                except ValueError:
                    continue

                if not any(rel.match(p) for p in patterns):
                    continue
                if not changed.is_file():
                    continue

                content = changed.read_bytes()
                content_hash = xxhash.xxh3_128(content).digest()
                mime_type = _MIME_MAP.get(changed.suffix.lower(), "application/octet-stream")
                yield SourceRecord(
                    iri=changed.as_uri(),
                    path=changed,
                    content=content,
                    content_hash=content_hash,
                    mime_type=mime_type,
                )
        finally:
            observer.stop()
            observer.join()
