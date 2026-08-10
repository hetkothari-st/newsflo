from backfill_domains import domain_from_website


def test_full_url_with_path_reduces_to_bare_host():
    assert domain_from_website("https://www.ril.com/investors") == "ril.com"


def test_bare_domain_passes_through():
    assert domain_from_website("nvidia.com") == "nvidia.com"


def test_www_stripped_scheme_optional():
    assert domain_from_website("http://www.tcs.com") == "tcs.com"


def test_empty_and_none_yield_none():
    assert domain_from_website(None) is None
    assert domain_from_website("") is None
