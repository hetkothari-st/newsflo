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
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
