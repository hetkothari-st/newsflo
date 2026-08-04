import pytest

from app.companies.matching import normalize


@pytest.mark.parametrize("raw,expected", [
    ("Reliance Industries Limited", "reliance industries"),
    ("Reliance Industries Ltd.", "reliance industries"),
    ("RELIANCE INDUSTRIES LTD", "reliance industries"),
    ("  Reliance   Industries  Ltd  ", "reliance industries"),
    ("Tata Consultancy Services Limited", "tata consultancy services"),
    ("Bajaj Finserv Ltd", "bajaj finserv"),
])
def test_legal_suffixes_are_stripped(raw, expected):
    assert normalize.normalize_name(raw) == expected


def test_ampersand_is_expanded():
    assert normalize.normalize_name("Procter & Gamble") == "procter and gamble"


def test_punctuation_is_removed():
    assert normalize.normalize_name("J.B. Chemicals") == "jb chemicals"


def test_india_is_never_stripped():
    # Stripping geography tokens manufactures collisions -- see spec 8.1.
    assert normalize.normalize_name("Apollo Hospitals") != normalize.normalize_name("Apollo Tyres")
    assert "india" in normalize.normalize_name("Oil India Limited")


def test_bharat_is_never_stripped():
    assert "bharat" in normalize.normalize_name("Bharat Gears Ltd")
    assert normalize.normalize_name("Bharat Gears Ltd") != normalize.normalize_name("Bharat Seats Ltd")


def test_suffix_only_stripped_at_the_end():
    # "Co" inside a name is a real word, not a suffix.
    assert normalize.normalize_name("Coal India Ltd") == "coal india"


def test_empty_and_none_are_safe():
    assert normalize.normalize_name(None) == ""
    assert normalize.normalize_name("   ") == ""


def test_multiple_trailing_suffixes_are_all_stripped():
    assert normalize.normalize_name("Some Name Pvt Ltd") == "some name"


def test_tokens_ignore_order():
    assert normalize.tokens("Reliance Industries Ltd") == normalize.tokens("Industries Reliance")


def test_tokens_of_empty_is_empty():
    assert normalize.tokens("") == frozenset()


def test_hyphen_and_parens_split_into_separate_tokens():
    assert normalize.normalize_name("Agri-Tech (India) Limited") == "agri tech india"


def test_hyphen_splits_in_embedded_word():
    assert normalize.normalize_name("BLS E-Services Limited") == "bls e services"


def test_dots_join_with_no_separator():
    assert normalize.normalize_name("D.B.Corp Limited") == "dbcorp"


def test_hyphenated_and_spaced_forms_produce_same_tokens():
    # The token-set match rung depends on this equality: a news mention
    # rendering "Agri Tech India" must collide with the registry's
    # "Agri-Tech India".
    assert normalize.tokens("Agri-Tech India") == normalize.tokens("Agri Tech India")
