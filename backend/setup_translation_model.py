"""One-time setup: download NLLB-200-distilled-1.3B and convert it to an
int8-quantized CTranslate2 model for fast CPU inference. Run once per
environment (a fresh dev machine, a fresh deploy target) before translation
can use TRANSLATION_PROVIDER = "nllb" -- app/translation/nllb_translator.py
expects the converted model to already exist at MODEL_DIR.

    .venv/Scripts/python setup_translation_model.py

Downloads ~5GB from HuggingFace (the fp32 source checkpoint) and writes out
a ~1.3GB int8 CTranslate2 model directory; the fp32 HuggingFace cache is not
needed afterward and can be cleared separately if disk space matters.
"""

import subprocess
import sys

from app.translation.nllb_translator import MODEL_DIR, TOKENIZER_NAME

if __name__ == "__main__":
    subprocess.run(
        [
            sys.executable, "-m", "ctranslate2.converters.transformers",
            "--model", TOKENIZER_NAME,
            "--output_dir", MODEL_DIR,
            "--quantization", "int8",
            "--force",
        ],
        check=True,
    )
    print(f"Model ready at {MODEL_DIR}")
