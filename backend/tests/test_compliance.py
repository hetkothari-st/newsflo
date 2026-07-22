from app.reasoning.compliance import validate_no_advice_language, validate_or_none


def test_rejects_percentage_figure():
    result = validate_no_advice_language("Analysts expect ~5% upside from here")
    assert result.is_valid is False
    assert "percentage" in result.reason


def test_rejects_negative_percentage_figure():
    result = validate_no_advice_language("The stock could see -3.5% downside")
    assert result.is_valid is False


def test_rejects_price_target_phrase():
    result = validate_no_advice_language("We set a price target of 500 for this stock")
    assert result.is_valid is False
    assert "price-target" in result.reason


def test_rejects_target_price_word_order_too():
    result = validate_no_advice_language("Our target price is under review")
    assert result.is_valid is False


def test_rejects_buy_sell_hold_language():
    for word in ["buy", "sell", "hold", "overweight", "underweight"]:
        result = validate_no_advice_language(f"We recommend investors {word} this stock")
        assert result.is_valid is False, f"{word!r} should have been rejected"


def test_accepts_clean_causal_text():
    result = validate_no_advice_language(
        "A weaker rupee raises the value of this company's dollar-denominated export revenue."
    )
    assert result.is_valid is True
    assert result.reason is None


def test_accepts_empty_or_none_text():
    assert validate_no_advice_language("").is_valid is True
    assert validate_no_advice_language(None).is_valid is True


def test_validate_or_none_returns_text_when_valid():
    text = "A rate cut lowers borrowing costs for this lender's customers."
    assert validate_or_none(text) == text


def test_validate_or_none_returns_none_when_invalid():
    assert validate_or_none("Expect ~5% upside") is None


def test_validate_or_none_passes_through_none():
    assert validate_or_none(None) is None
