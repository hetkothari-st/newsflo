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

# Where translation model weights live. Set explicitly (rather than left to
# HuggingFace's default under $HOME) so the cache a build step populates is
# the same directory the running container reads -- otherwise the prefetch
# below lands somewhere the app never looks and every boot re-downloads.
ENV HF_HOME=/app/models/hf

# Which translation models to bake into the image. Both default to the
# behaviour of the branch they are on rather than being flipped per
# environment, because a missing model is a slow runtime download, not an
# error -- both providers load lazily and will fetch on first use if the
# cache is cold (see indictrans2_translator._get_model).
#
# NLLB is ~5GB to download and convert; IndicTrans2 is ~1GB and needs no
# conversion. Skipping the one you are not using is most of the build time.
ARG BAKE_NLLB=0
ARG BAKE_INDICTRANS2=1

# Self-hosted NLLB translation model (see app/translation/nllb_translator.py)
# -- downloaded and int8-quantized at build time so the running container
# never depends on HuggingFace at runtime. Its own layer, before COPY
# backend/ ./, so ordinary code changes don't force this ~5GB download to
# repeat on every build. MODEL_DIR there is relative ("models/...") and
# resolves against WORKDIR /app, matching the absolute path below.
RUN if [ "$BAKE_NLLB" = "1" ]; then \
      python -m ctranslate2.converters.transformers \
        --model facebook/nllb-200-distilled-1.3B \
        --output_dir /app/models/nllb-200-distilled-1.3B-int8 \
        --quantization int8 ; \
    else \
      echo "skipping NLLB bake (BAKE_NLLB=$BAKE_NLLB)" ; \
    fi

# IndicTrans2 (see app/translation/indictrans2_translator.py). Warms the HF
# cache under HF_HOME rather than converting -- CTranslate2 has no loader for
# this architecture, so it runs as a plain transformers model. Same layer
# ordering rationale as NLLB above: before the source COPY, so editing code
# does not re-download ~1GB.
#
# trust_remote_code is required (custom architecture + slow tokenizer) and is
# the reason requirements.txt pins transformers to 4.x.
ARG INDICTRANS2_MODEL=naklitechie/indictrans2-en-indic-dist-200M
RUN if [ "$BAKE_INDICTRANS2" = "1" ]; then \
      python -c "\
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer; \
m='${INDICTRANS2_MODEL}'; \
AutoTokenizer.from_pretrained(m, trust_remote_code=True); \
AutoModelForSeq2SeqLM.from_pretrained(m, trust_remote_code=True); \
print('IndicTrans2 cached')" ; \
    else \
      echo "skipping IndicTrans2 bake (BAKE_INDICTRANS2=$BAKE_INDICTRANS2)" ; \
    fi

COPY backend/ ./
COPY --from=frontend-build /frontend/dist ./app/static
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
