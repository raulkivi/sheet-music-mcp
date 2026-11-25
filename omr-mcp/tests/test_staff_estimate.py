"""Staves per system from the image alone (proposal 5.5, AC-O3): the input of the SATB warning.

Real-page evidence is in tests/test_staff_estimate_samples.py (integration).
"""

import pytest
from PIL import Image, ImageDraw

from omr_mcp.staff_estimate import estimate_staves


def _page(
    tmp_path,
    systems,
    *,
    width=800,
    spacing=10,
    thickness=1,
    coverage=1.0,
    staff_gap=60,
    system_gap=120,
    joined=True,
    name="page.png",
):
    """White page; ``systems`` lists the staves per system, top to bottom.

    Staves of one system sit ``staff_gap`` px apart and, when ``joined``, share the system line at
    their left end, as engraved scores draw it. Lines span ``coverage`` of the width.
    """
    staff_height = 4 * spacing
    height = 120 + sum(n * (staff_height + staff_gap) + system_gap for n in systems)
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    left, right = 20, 20 + int((width - 40) * coverage)
    y = 60
    for staves in systems:
        first_top = y
        for _ in range(staves):
            for line in range(5):
                top = y + line * spacing
                draw.rectangle([left, top, right, top + thickness - 1], fill=0)
            last_bottom = y + staff_height + thickness - 1
            y += staff_height + staff_gap
        if joined and staves > 1:
            draw.rectangle([left, first_top, left + thickness - 1, last_bottom], fill=0)
        y += system_gap
    path = tmp_path / name
    image.save(path)
    return path


@pytest.mark.parametrize("staves", [1, 2, 4, 6])
def test_counts_the_staves_of_one_system(tmp_path, staves):
    assert estimate_staves(_page(tmp_path, [staves])) == staves


def test_an_satb_page_of_three_systems_counts_four(tmp_path):
    assert estimate_staves(_page(tmp_path, [4, 4, 4])) == 4


def test_a_one_staff_page_counts_one_however_many_lines_of_music(tmp_path):
    # A melody page: one-staff systems never share a system line.
    assert estimate_staves(_page(tmp_path, [1] * 8)) == 1


def test_piano_grand_staves_count_two(tmp_path):
    assert estimate_staves(_page(tmp_path, [2, 2, 2])) == 2


def test_the_largest_system_wins_when_empty_staves_are_hidden(tmp_path):
    # Scores that hide empty staves print systems of different sizes on one page.
    assert estimate_staves(_page(tmp_path, [4, 6, 3])) == 6


def test_staves_without_a_system_line_are_separate_systems(tmp_path):
    assert estimate_staves(_page(tmp_path, [4], joined=False)) == 1


def test_a_short_vertical_mark_between_staves_does_not_join_them(tmp_path):
    path = _page(tmp_path, [1, 1], system_gap=60)
    image = Image.open(path)
    # A stem reaching halfway into the gap below the first staff.
    ImageDraw.Draw(image).rectangle([400, 100, 400, 130], fill=0)
    image.save(path)

    assert estimate_staves(path) == 1


def test_a_page_frame_outside_the_staves_does_not_join_them(tmp_path):
    path = _page(tmp_path, [1, 1, 1], width=900, coverage=0.8)
    image = Image.open(path)
    # A scan shadow or printed border down the right margin, clear of the staves' ends.
    ImageDraw.Draw(image).rectangle([880, 0, 884, image.height - 1], fill=0)
    image.save(path)

    assert estimate_staves(path) == 1


def test_a_slightly_skewed_system_line_still_joins(tmp_path):
    path = _page(tmp_path, [4], joined=False)
    image = Image.open(path)
    draw = ImageDraw.Draw(image)
    # Leans one pixel over the system's height, as a scan a little off square does.
    draw.line([(20, 60), (21, 60 + 3 * 100 + 40)], fill=0)
    image.save(path)

    assert estimate_staves(path) == 4


@pytest.mark.parametrize("degrees", [-1.5, -0.3, 0.2, 0.8, 2.0])
def test_a_page_scanned_a_little_off_square_still_counts(tmp_path, degrees):
    path = _page(tmp_path, [4, 4], width=1200, thickness=2, spacing=12)
    Image.open(path).rotate(degrees, resample=Image.BICUBIC, fillcolor=255).save(path)

    assert estimate_staves(path) == 4


def test_a_tilted_melody_page_still_counts_one(tmp_path):
    path = _page(tmp_path, [1] * 6, width=1200, thickness=2, spacing=12)
    Image.open(path).rotate(1.0, resample=Image.BICUBIC, fillcolor=255).save(path)

    assert estimate_staves(path) == 1


def test_thin_lines_smoothed_to_gray_still_count(tmp_path):
    # Downscaled or rotated renders: a one-pixel line turns mid-gray, lighter than half ink.
    path = _page(tmp_path, [4])
    image = Image.open(path).point(lambda v: 160 if v == 0 else v)
    image.save(path)

    assert estimate_staves(path) == 4


def test_grey_paper_is_not_ink(tmp_path):
    # A photo: the paper is mid-gray and the ink is not black.
    path = _page(tmp_path, [4, 4])
    image = Image.open(path).point(lambda v: 70 if v == 0 else 185)
    image.save(path)

    assert estimate_staves(path) == 4


def test_thick_lines_still_count_once_each(tmp_path):
    assert estimate_staves(_page(tmp_path, [4], thickness=3, spacing=14)) == 4


def test_staves_that_span_half_the_page_count(tmp_path):
    assert estimate_staves(_page(tmp_path, [3], coverage=0.55)) == 3


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


def test_unevenly_spaced_rules_are_not_a_staff(tmp_path):
    # A title page: frame rules and the strokes of large letters, nothing like five even lines.
    path = tmp_path / "title.png"
    image = Image.new("L", (800, 900), 255)
    draw = ImageDraw.Draw(image)
    for y in (80, 95, 290, 365, 500):
        draw.rectangle([20, y, 780, y + 2], fill=0)
    image.save(path)

    assert estimate_staves(path) == 0


def test_evenly_spaced_broken_strokes_are_not_a_staff(tmp_path):
    # Large title letters: their tops and bars line up in rows, but with gaps between the letters.
    path = tmp_path / "letters.png"
    image = Image.new("L", (800, 900), 255)
    draw = ImageDraw.Draw(image)
    for y in (210, 283, 345, 418):
        for x in range(20, 780, 60):
            draw.rectangle([x, y, x + 39, y + 3], fill=0)
    image.save(path)

    assert estimate_staves(path) == 0


def test_a_long_beam_between_two_staff_lines_does_not_hide_the_staff(tmp_path):
    path = _page(tmp_path, [3])
    image = Image.open(path)
    # A beam or tremolo row across most of the second staff, between its 3rd and 4th lines.
    ImageDraw.Draw(image).rectangle([60, 160 + 24, 700, 160 + 25], fill=0)
    image.save(path)

    assert estimate_staves(path) == 3


def test_a_staff_with_one_faint_line_still_counts(tmp_path):
    path = _page(tmp_path, [2])
    image = Image.open(path)
    # Paint out most of the middle line of the lower staff (a faded scan).
    ImageDraw.Draw(image).rectangle([100, 60 + 100 + 20, 780, 60 + 100 + 20], fill=255)
    image.save(path)

    assert estimate_staves(path) == 2


def test_colour_and_transparent_images_are_read(tmp_path):
    Image.open(_page(tmp_path, [2])).convert("RGBA").save(tmp_path / "rgba.png")

    assert estimate_staves(tmp_path / "rgba.png") == 2


def test_an_unreadable_image_gives_none(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")

    assert estimate_staves(path) is None
    assert estimate_staves(tmp_path / "missing.png") is None
