from app.ingestion.urltools import canonical_url_hash, canonicalize_url


def test_canonicalize_strips_tracking_params_host_case_and_trailing_slash():
    assert (
        canonicalize_url("https://EX.com/Path/?utm_source=x&utm_campaign=y&id=7&fbclid=z")
        == "https://ex.com/Path?id=7"
    )


def test_canonicalize_preserves_identifying_params_and_path_case():
    assert canonicalize_url("https://ex.com/a?page=2") == "https://ex.com/a?page=2"
    # Path case can be significant -- only scheme/host lowercase.
    assert canonicalize_url("https://ex.com/CaseSensitive") == "https://ex.com/CaseSensitive"


def test_hash_equal_for_decoration_variants_only():
    a = canonical_url_hash("https://ex.com/story?utm_source=rss")
    b = canonical_url_hash("https://EX.com/story/")
    c = canonical_url_hash("https://ex.com/story?id=2")
    assert a == b
    assert a != c
