"""Staff counting from the image alone (proposal 5.5, AC-O3): the input of the SATB warning."""

import pytest
from PIL import Image, ImageDraw

from omr_mcp.staff_estimate import estimate_staves


def _page(tmp_path, staves, *, width=800, spacing=10, thickness=1, coverage=1.0, name="page.png"):
    """White page with ``staves`` five-line staves, 80 px clear of each other, lines over ``coverage`` of the width."""
    height = 100 + staves * (4 * spacing + 80)
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for s in range(staves):
        top = 60 + s * (4 * spacing + 80)
        for line in range(5):
            y = top + line * spacing
            draw.rectangle([20, y, 20 + int((width - 40) * coverage), y + thickness - 1], fill=0)
    path = tmp_path / name
    image.save(path)
    return path


@pytest.mark.parametrize("staves", [1, 2, 4, 6])
def test_counts_the_staves(tmp_path, staves):
    assert estimate_staves(_page(tmp_path, staves)) == staves


def test_thick_lines_still_count_once_each(tmp_path):
    assert estimate_staves(_page(tmp_path, 4, thickness=3, spacing=14)) == 4


def test_staves_that_span_half_the_page_count(tmp_path):
    assert estimate_staves(_page(tmp_path, 3, coverage=0.55)) == 3


def test_a_blank_page_has_no_staves(tmp_path):
    path = tmp_path / "blank.png"
    Image.new("L", (400, 400), 255).save(path)

    assert estimate_staves(path) == 0


def test_a_lone_rule_is_not_a_staff(tmp_path):
    path = tmp_path / "rule.png"
    image = Image.new("L", (800, 400), 255)
    ImageDraw.Draw(image).rectangle([20, 200, 780, 200], fill=0)
    image.save(path)

    assert estimate_staves(path) == 0


def test_colour_and_transparent_images_are_read(tmp_path):
    Image.open(_page(tmp_path, 2)).convert("RGBA").save(tmp_path / "rgba.png")

    assert estimate_staves(tmp_path / "rgba.png") == 2


def test_an_unreadable_image_gives_none(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")

    assert estimate_staves(path) is None
    assert estimate_staves(tmp_path / "missing.png") is None
