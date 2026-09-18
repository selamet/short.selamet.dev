from apps.links import utm


def test_presets_cover_the_design_and_carry_source_and_medium():
    assert list(utm.UTM_PRESETS) == [
        "instagram-bio",
        "instagram-story",
        "tiktok-profile",
        "youtube-description",
        "newsletter",
    ]
    for preset in utm.UTM_PRESETS.values():
        assert preset["label"]
        assert preset["params"]["utm_source"]
        assert preset["params"]["utm_medium"]


def test_apply_preset_fills_campaign_when_given():
    applied = utm.apply_preset("instagram-bio", campaign="spring26")
    assert applied["utm_source"] == "instagram"
    assert applied["utm_medium"] == "bio"
    assert applied["utm_campaign"] == "spring26"


def test_apply_preset_of_unknown_key_is_empty():
    assert utm.apply_preset("nope") == {}


def test_merge_utm_appends_without_overriding_existing_parameters():
    merged = utm.merge_utm(
        "https://example.com/p?utm_source=keep&x=1",
        {"utm_source": "instagram", "utm_medium": "bio", "utm_campaign": ""},
    )
    assert "utm_source=keep" in merged
    assert "utm_medium=bio" in merged
    assert "utm_campaign" not in merged
    assert "x=1" in merged


def test_merge_utm_leaves_the_url_untouched_when_there_is_nothing_to_add():
    assert utm.merge_utm("https://example.com/p", {}) == "https://example.com/p"
