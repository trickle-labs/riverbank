# Configure Label Studio

The human review loop routes low-confidence extractions to Label Studio for manual validation. Reviewers accept, correct, or reject each extraction, and their decisions flow back into the graph.

## Prerequisites

- Label Studio running (via Docker Compose or standalone)
- An API key with project-level access
- riverbank installed with `[review]` extras

## Step 1: Start Label Studio

If using Docker Compose, Label Studio is included:

```bash
docker compose up -d label-studio
```

Or run standalone:

```bash
docker run -p 8080:8080 heartexlabs/label-studio:latest
```

## Step 2: Queue low-confidence extractions

```bash
riverbank review queue \
  --graph http://riverbank.example/graph/trusted \
  --limit 20 \
  --ls-url http://localhost:8080 \
  --ls-key "your-api-key" \
  --ls-project 0
```

With `--ls-project 0`, riverbank auto-creates a project. The queue selects the 20 extractions with the lowest confidence scores (centrality × uncertainty ranking).

## Step 3: Review in Label Studio

Open Label Studio at `http://localhost:8080`. Each task shows:

- The extracted triple (subject, predicate, object)
- The confidence score
- The evidence span with source context
- Accept / Correct / Reject buttons

## Step 4: Collect decisions

After reviewers annotate tasks:

```bash
riverbank review collect \
  --profile docs-policy-v1 \
  --ls-url http://localhost:8080 \
  --ls-key "your-api-key" \
  --ls-project 1
```

This:

1. Fetches completed annotations from Label Studio
2. Writes accepted/corrected decisions to the `<human-review>` named graph
3. Exports each decision to the profile's few-shot example bank

## Step 5: Dry-run mode

To inspect candidates without touching Label Studio:

```bash
riverbank review queue --dry-run --limit 10
```

## The feedback loop

Collected decisions improve future extractions in two ways:

1. **Graph corrections** — corrected triples replace the originals in the trusted graph
2. **Example bank** — each decision becomes a few-shot example for the extractor, improving accuracy on similar content in future runs
