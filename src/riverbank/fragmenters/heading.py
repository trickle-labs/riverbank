from __future__ import annotations

from typing import ClassVar, Iterator


class HeadingFragmenter:
    """Heading-based document fragmenter.

    Splits a parsed document at every Markdown heading boundary, producing
    one Fragment per section.  Full implementation arrives in v0.2.0.
    """

    name: ClassVar[str] = "heading"

    def fragment(self, doc: object) -> Iterator[object]:
        raise NotImplementedError("HeadingFragmenter not yet implemented — arriving in v0.2.0")
        # ``yield`` keeps the type-checker happy — this is a generator stub
        yield  # type: ignore[misc]
