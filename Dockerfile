# ─── builder stage ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install core + ingest extras (NLP deps needed at runtime)
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir ".[ingest]"

# Pre-download sentence-transformer embedding models so the image runs
# fully offline and the HF Hub rate-limit warning never appears at runtime.
# The models are stored inside the virtualenv cache layer.
ENV HF_HOME=/opt/hf-cache
RUN python -m riverbank.fragmenters.semantic --download-models || \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2'); print('models cached')" 2>&1

# ─── runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Non-root user
RUN groupadd --system riverbank && useradd --system --gid riverbank riverbank

# Copy the virtualenv from the builder (includes riverbank itself)
COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV

# Copy the pre-downloaded HF model cache
COPY --from=builder /opt/hf-cache /opt/hf-cache

# Point sentence-transformers at the pre-cached models; no network needed
ENV HF_HOME=/opt/hf-cache
# Silence the unauthenticated-request warning — we are using the local cache
ENV HF_HUB_DISABLE_PROGRESS_BARS=1
ENV TRANSFORMERS_OFFLINE=1
ENV HF_DATASETS_OFFLINE=1

# Copy alembic config so `riverbank init` can find migration scripts
COPY alembic.ini ./
COPY src/ src/

USER riverbank

ENTRYPOINT ["riverbank"]
CMD ["--help"]
