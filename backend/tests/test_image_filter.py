from app.ingestion.image_filter import (
    displayable_image_url,
    is_generic_image_filename,
    repeated_image_urls,
    resolve_article_image,
)
from app.models import Article


def test_logo_and_placeholder_filenames_are_generic():
    assert is_generic_image_filename("https://capitalmarket.com/markets/images/cmlogo1.png")
    assert is_generic_image_filename("https://x.com/img/og-image.jpg")
    assert is_generic_image_filename("https://x.com/assets/default_1200x630.png")


def test_real_photo_filenames_are_not_generic():
    # A /logo/ DIRECTORY holding a real photo must not match -- only the
    # basename is checked (observed: livemint stores story photos under
    # /lm-img/.../logo/<real-photo>.jpg).
    assert not is_generic_image_filename(
        "https://www.livemint.com/lm-img/img/2026/07/17/1600x900/logo/Picture_-_Federal_Bank_Branch.jpg"
    )
    assert not is_generic_image_filename(
        "https://img.etimg.com/thumb/msid-132455021,width-1200,height-630/articleshow.jpg"
    )
    # A newspaper's default banner whose filename carries no telltale
    # token is NOT caught here -- the repetition signal handles it (it
    # appears on every wire story the paper republishes).
    assert not is_generic_image_filename(
        "https://www.business-standard.com/assets/web-assets/images/Business_Standard_1_685x385.jpg"
    )


def test_repeated_image_urls_flags_boilerplate(db_session):
    boilerplate = "https://pub.example.com/images/photo-banner.jpg"
    unique = "https://pub.example.com/images/story-shot.jpg"
    for i in range(3):
        db_session.add(Article(source="pub", url=f"https://pub.example.com/{i}", title="t", image_url=boilerplate))
    db_session.add(Article(source="pub", url="https://pub.example.com/u", title="t", image_url=unique))
    db_session.commit()

    repeated = repeated_image_urls(db_session, [boilerplate, unique])
    assert repeated == {boilerplate}


def test_resolve_keeps_clean_provided_image_without_fetching():
    def _fetch_should_not_run(url):
        raise AssertionError("no HTTP fetch when the provided image is already clean")

    assert (
        resolve_article_image("https://pub.example.com/story", "https://x.com/story-shot.jpg", fetch=_fetch_should_not_run)
        == "https://x.com/story-shot.jpg"
    )


def test_resolve_refetches_page_photo_when_provided_image_is_a_logo():
    # Finnhub hands a wire-service logo -> fetch the article page's own
    # og:image (the real photo) instead.
    assert (
        resolve_article_image(
            "https://pub.example.com/story", "https://cdn.example.com/reuters-logo.png",
            fetch=lambda url: "https://pub.example.com/photos/real-shot.jpg",
        )
        == "https://pub.example.com/photos/real-shot.jpg"
    )


def test_resolve_keeps_original_when_refetch_finds_nothing_better():
    # og fetch fails -> keep the (generic) original; the serve-time filter
    # hides it rather than this function inventing anything.
    assert (
        resolve_article_image(
            "https://pub.example.com/story", "https://cdn.example.com/reuters-logo.png",
            fetch=lambda url: None,
        )
        == "https://cdn.example.com/reuters-logo.png"
    )
    # og fetch returns another logo -> also keep the original.
    assert (
        resolve_article_image(
            "https://pub.example.com/story", "https://cdn.example.com/reuters-logo.png",
            fetch=lambda url: "https://pub.example.com/site-logo.png",
        )
        == "https://cdn.example.com/reuters-logo.png"
    )


def test_resolve_refetches_when_provided_image_is_repetition_condemned():
    # Clean filename but flagged by the repetition signal (wire-service
    # boilerplate) -> must still re-fetch the real photo.
    assert (
        resolve_article_image(
            "https://pub.example.com/story", "https://ml.example.com/Resource/banner-photo.jpg",
            fetch=lambda url: "https://pub.example.com/photos/real-shot.jpg",
            provided_is_generic=True,
        )
        == "https://pub.example.com/photos/real-shot.jpg"
    )


def test_resolve_fetches_when_no_image_provided():
    assert (
        resolve_article_image(
            "https://pub.example.com/story", None,
            fetch=lambda url: "https://pub.example.com/photos/real-shot.jpg",
        )
        == "https://pub.example.com/photos/real-shot.jpg"
    )
    assert resolve_article_image("https://pub.example.com/story", None, fetch=lambda url: None) is None


def test_resolve_google_wrapper_fetches_from_the_real_publisher_url():
    fetched_from = []

    def _fetch(url):
        fetched_from.append(url)
        return "https://publisher.example.com/photos/real-shot.jpg"

    result = resolve_article_image(
        "https://news.google.com/rss/articles/OPAQUE123",
        "https://static2.finnhub.io/file/finnhub/logo/reuters_logo.jpeg",
        fetch=_fetch,
        resolve_wrapper=lambda url: "https://publisher.example.com/story",
    )
    assert result == "https://publisher.example.com/photos/real-shot.jpg"
    assert fetched_from == ["https://publisher.example.com/story"]


def test_resolve_skips_og_fetch_when_google_wrapper_resolution_fails():
    # Fetching the wrapper page itself would only harvest Google's own
    # logo -- when resolution fails there must be NO og fetch at all.
    def _fetch_should_not_run(url):
        raise AssertionError("no og fetch against an unresolved Google News wrapper")

    result = resolve_article_image(
        "https://news.google.com/rss/articles/OPAQUE123",
        "https://static2.finnhub.io/file/finnhub/logo/reuters_logo.jpeg",
        fetch=_fetch_should_not_run,
        resolve_wrapper=lambda url: None,
    )
    assert result == "https://static2.finnhub.io/file/finnhub/logo/reuters_logo.jpeg"


def test_google_news_url_detection_and_id_extraction():
    from app.ingestion.google_news import _article_id, is_google_news_url

    assert is_google_news_url("https://news.google.com/rss/articles/CBMiwAFBVV95?oc=5")
    assert not is_google_news_url("https://www.reuters.com/world/a-story/")
    assert _article_id("https://news.google.com/rss/articles/CBMiwAFBVV95?oc=5") == "CBMiwAFBVV95"
    assert _article_id("https://news.google.com/read/CBMiabc") == "CBMiabc"
    assert _article_id("https://news.google.com/home") is None


def test_displayable_image_url_nulls_generic_and_repeated():
    repeated = {"https://pub.example.com/images/photo-banner.jpg"}
    assert displayable_image_url(None, repeated) is None
    assert displayable_image_url("https://pub.example.com/images/photo-banner.jpg", repeated) is None
    assert displayable_image_url("https://x.com/cmlogo1.png", set()) is None
    assert (
        displayable_image_url("https://x.com/story-shot.jpg", repeated)
        == "https://x.com/story-shot.jpg"
    )
