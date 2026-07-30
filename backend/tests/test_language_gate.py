from app.filtering.language_gate import is_english_text


def test_english_headlines_pass():
    assert is_english_text("American Airlines resumes flights after IT issue forced brief halt")
    assert is_english_text("TSG Consumer to Acquire Majority Stake in Saltair")
    assert is_english_text("RBI holds rates, tightens NBFC funding norms")


def test_non_latin_scripts_fail():
    # Japanese / Arabic / Hindi wire mirrors (observed in production).
    assert not is_english_text("Copeland、DicksonのIntelligrated事業買収を発表")
    assert not is_english_text("كوبلاند تعلن عن مفاوضات حصرية")
    assert not is_english_text("कोपलैंड ने विशेष वार्ता शुरू की")


def test_latin_script_foreign_languages_fail():
    # Spanish / French / German mirrors look pure-ASCII -- caught by the
    # stopword ratio, not the script test.
    assert not is_english_text("Copeland inicia negociaciones exclusivas para la venta de su negocio")
    assert not is_english_text("Copeland annonce des négociations exclusives pour la vente")
    assert not is_english_text("Copeland gibt exklusive Verhandlungen für den Verkauf bekannt")


def test_no_signal_fails_open_as_english():
    # Tickers/numbers only -- no language signal, admit rather than drop.
    assert is_english_text("RELIANCE.NS +4.2% 52W")
    assert is_english_text("")
