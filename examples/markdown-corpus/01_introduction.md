# Introduction to Ariadne

Ariadne is an open-source Python library for managing structured research threads.
It was created by Dr. Elena Vasquez at the Meridian Institute in 2023 and released
under the Apache 2.0 licence.

## What problem does Ariadne solve?

Research teams frequently accumulate large bodies of notes, papers, and observations
across multiple projects. Ariadne addresses the **information fragmentation problem**
by providing a unified graph-based model for linking concepts, claims, and evidence.

Key design goals:

- **Traceability** — every claim links back to the source document and author
- **Composability** — knowledge graphs from separate projects can be merged
- **Incremental updates** — new evidence can update confidence scores without
  reprocessing the entire corpus

## Core concepts

### Thread

A *thread* is a named investigation. It has an owner, a creation date, and a
set of contributing authors. Example: `"battery-degradation-study-2024"`.

### Node

A *node* represents an atomic claim. Each node carries:

- a subject IRI
- a predicate IRI
- an object (literal or IRI)
- a confidence score (0–1)
- one or more evidence spans pointing to source text

### Edge

An *edge* connects two nodes when one claim depends on or contradicts another.

## Licensing

Ariadne is maintained by the Meridian Institute and released under the
Apache 2.0 licence. Commercial support is available from Meridian Labs Ltd.
