from __future__ import annotations

from typing import ClassVar, Iterator


class FileReviewer:
    """File-based review back-end (writes review tasks to a JSONL file).

    Used for offline / air-gapped review workflows.
    Full implementation arrives in v0.5.0 alongside the Label Studio reviewer.
    """

    name: ClassVar[str] = "file"

    def enqueue(self, task: object) -> None:
        raise NotImplementedError("FileReviewer not yet implemented — arriving in v0.5.0")

    def collect(self) -> Iterator[object]:
        raise NotImplementedError("FileReviewer not yet implemented — arriving in v0.5.0")
        yield  # type: ignore[misc]
