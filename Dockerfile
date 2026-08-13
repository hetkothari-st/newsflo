FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Self-hosted NLLB translation model (see app/translation/nllb_translator.py)
# -- downloaded and int8-quantized at build time so the running container
# never depends on HuggingFace at runtime. Its own layer, before COPY
# backend/ ./, so ordinary code changes don't force this ~5GB download to
# repeat on every build. MODEL_DIR there is relative ("models/...") and
# resolves against WORKDIR /app, matching the absolute path below.
RUN python -m ctranslate2.converters.transformers \
    --model facebook/nllb-200-distilled-1.3B \
    --output_dir /app/models/nllb-200-distilled-1.3B-int8 \
    --quantization int8

COPY backend/ ./
COPY --from=frontend-build /frontend/dist ./app/static
# Migrations run at boot, BEFORE uvicorn -- schema ownership moved to
# Alembic (app/db.py's _ADDED_COLUMNS is frozen), so init_db() alone can no
# longer add a column to a PRE-EXISTING database. Without this step every
# column added by 0002+ was missing in production while the code wrote it
# unconditionally. `&&` is load-bearing: a failed migration must abort the
# container, never leave it serving a half-migrated schema.
CMD ["sh", "-c", "python tools/migrate_on_boot.py && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
