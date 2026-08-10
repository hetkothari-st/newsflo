"""Canonical-URL hashing for cross-provider dedup.

Two providers reporting the same story usually disagree only in URL
decoration -- tracking parameters, host case, a trailing slash. Hashing a
canonicalized form catches those; genuinely different URLs for the same
story are left to the downstream exact-title dedup
(app.pipeline._find_reusable_alert), which is deliberately conservative.
"""
import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Parameters that never identify content, only the click's provenance.
# Removing an identifying param would merge two different articles, so this
# list holds only the universally understood tracking families.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "cmpid", "smid"}


def canonicalize_url(url: str) -> str:
    try:
        scheme, netloc, path, query, _fragment = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    netloc = netloc.lower()
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
    kept = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
        and not key.lower().startswith(_TRACKING_PARAM_PREFIXES)
    ]
    return urlunsplit((scheme.lower(), netloc, path, urlencode(kept), ""))


def canonical_url_hash(url: str) -> str:
    return hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()
