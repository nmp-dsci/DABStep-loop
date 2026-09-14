# The demo image: the public, read-only deployment.
#
# One container, no database, no secrets. Everything a visitor browses is baked
# in at build time — the committed data sample, the run folders, the ledger,
# the registry, the recorded demo pack, the MLflow snapshot — so what a given
# image serves is exactly what its commit says it serves.
#
# DEMO_MODE is set here rather than in infrastructure, deliberately: the image
# itself is the thing that cannot make model calls, so no Terraform mistake or
# console edit can turn a public URL into a billable one. There is no API key
# and no CLI login in the environment for it to use either.
#
#   docker build -t dabstep-demo .
#   docker run --rm -p 8080:8080 dabstep-demo    # no env file, no keys

# ── Stage 1: frontend bundle ────────────────────────────────────────────
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: runtime ────────────────────────────────────────────────────
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first, as their own layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt \
    && uv pip install --system -r requirements.txt \
    && rm requirements.txt

# Code, UI, and the committed artifacts the read-only routes serve.
COPY src/ src/
COPY --from=frontend /build/dist frontend/dist
COPY data/samples/ data/samples/
COPY data/tasks/ data/tasks/
COPY data/file_structures.json data/
COPY agents/ agents/
COPY runs/ runs/
COPY loop/ loop/

# The build's git SHA, passed in by the deploy workflow.
ARG CODE_SHA=unknown
ENV DABSTEP_CODE_SHA=$CODE_SHA

ENV DEMO_MODE=1 \
    BILLING=none \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "dabstep_loop.serving.app:create_app", \
     "--factory", "--workers", "1", "--host", "0.0.0.0", "--port", "8080"]
