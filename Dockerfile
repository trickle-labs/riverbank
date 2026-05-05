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

# ─── runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Non-root user
RUN groupadd --system riverbank && useradd --system --gid riverbank riverbank

# Copy the virtualenv from the builder (includes riverbank itself)
COPY --from=builder $VIRTUAL_ENV $VIRTUAL_ENV

# Copy alembic config so `riverbank init` can find migration scripts
COPY alembic.ini ./
COPY src/ src/

USER riverbank

ENTRYPOINT ["riverbank"]
CMD ["--help"]
