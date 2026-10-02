# Two stages: Node builds the React app, then a slim Python image serves it with the API.
# The final image holds the built files only, not Node or node_modules.

# ---- stage 1: build the web app ----
FROM node:22-alpine AS web
WORKDIR /build/frontend
# Dependencies first, so this layer stays cached until package-lock.json changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# vite.config.ts writes the build to ../backend/app/static, i.e. /build/backend/app/static
RUN npm run build

# ---- stage 2: the server ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# git: cloning projects, and the agent's read-only git tools. Projects are mounted from the host and
# owned by another user, which git refuses by default ("dubious ownership"); trust them explicitly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'

WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY --from=web /build/backend/app/static ./app/static

# Run as a non-root user: a container escape then lands in an unprivileged account.
RUN useradd --create-home codeloop && mkdir -p /workspace && chown codeloop /workspace
USER codeloop

ENV CODELOOP_WORKSPACE_ROOT=/workspace
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
