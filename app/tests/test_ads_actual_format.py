"""F46 Contract F: the actual format of what ships is the uploaded file's -- a video original is
a video, any other file a single image; the slot's sentence when the plan says otherwise."""

import pytest

from app.ads import actual_format

LABELS = {"carousel": "輪播", "single_image": "單圖", "video": "影片"}


@pytest.mark.parametrize(
    ("asset", "expected"),
    [
        ({"mime_type": "video/mp4"}, "video"),
        ({"mime_type": "VIDEO/quicktime"}, "video"),
        ({"mime_type": "image/png"}, "single_image"),
        ({"mime_type": "image/jpeg"}, "single_image"),
        ({"mime_type": None}, "single_image"),  # a file of unknown type is still one file
        ({}, "single_image"),
        (None, None),  # no file, no actual format
    ],
)
def test_of_asset_reads_the_files_mime(asset, expected):
    assert actual_format.of_asset(asset) == expected


def test_a_carousel_with_one_image_reads_the_prototype_sentence():
    assert (
        actual_format.note("carousel", "single_image", LABELS)
        == "規劃是輪播，只放了 1 張圖，會以單圖上架"
    )


def test_any_other_difference_names_both_formats_in_the_brands_words():
    assert (
        actual_format.note("video", "single_image", LABELS)
        == "規劃是影片，放的是單圖，會以單圖上架"
    )
    assert (
        actual_format.note("single_image", "video", LABELS)
        == "規劃是單圖，放的是影片，會以影片上架"
    )


def test_a_key_without_a_vocabulary_label_prints_itself():
    assert (
        actual_format.note("story_9x16", "video", {})
        == "規劃是story_9x16，放的是video，會以video上架"
    )


@pytest.mark.parametrize(
    ("planned", "actual"),
    [("single_image", "single_image"), ("video", "video"), (None, "video"), ("carousel", None),
     (None, None)],
)
def test_no_note_when_equal_or_unknown(planned, actual):
    assert actual_format.note(planned, actual, LABELS) is None


def test_of_ad_without_material_is_none():
    assert actual_format.of_ad(None, "org", "brand", "campaign", {}) is None
    assert actual_format.of_ad(
        None, "org", "brand", "campaign", {"material_placement_id": None}
    ) is None
