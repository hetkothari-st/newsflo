from fastapi import Query

from app.translation.languages import normalize_lang


def get_lang(lang: str = Query("en")) -> str:
    """FastAPI dependency: clamps any unrecognized `?lang=` value to English
    rather than 422ing -- consistent with the rest of the feature's silent-
    fallback-to-English philosophy."""
    return normalize_lang(lang)
