from app.ingestion.image_filter import (
    displayable_image_url,
    is_generic_image_filename,
    repeated_image_urls,
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


def test_displayable_image_url_nulls_generic_and_repeated():
    repeated = {"https://pub.example.com/images/photo-banner.jpg"}
    assert displayable_image_url(None, repeated) is None
    assert displayable_image_url("https://pub.example.com/images/photo-banner.jpg", repeated) is None
    assert displayable_image_url("https://x.com/cmlogo1.png", set()) is None
    assert (
        displayable_image_url("https://x.com/story-shot.jpg", repeated)
        == "https://x.com/story-shot.jpg"
    )
