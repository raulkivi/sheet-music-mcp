"""``estimate_staves`` on the real sample pages (T2.2 evidence; results in docs/staff-estimate-evidence.md).

The samples are not in git (test_samples/ is ignored; download scripts live there). Set
``OMR_TEST_SAMPLES`` to another copy of that folder, for example the main checkout's from a
worktree. Each page is skipped when its file is absent, so CI skips them all.

Expected values were read off each page by eye: the staves of the largest system, counting a
piano part as 2 and an SA/TB short score as 2. Pages without music count 0.
"""

import os
from pathlib import Path

import pytest

from omr_mcp.staff_estimate import estimate_staves

pytestmark = pytest.mark.integration

SAMPLES = Path(os.environ.get("OMR_TEST_SAMPLES", Path(__file__).parent.parent / "test_samples"))

CPDL = "cpdl_satb_samples"
PDMX = "pdmx_satb_samples/png"
MUSICXML = "musicxml_samples"

# (page image under SAMPLES, staves in its largest system)
EXPECTED = [
    # CPDL choral editions (LilyPond and others)
    (f"{CPDL}/Ave_verum_corpus_-_William_Byrd/Ave_verum_corpus_-_William_Byrd_page01.png", 4),
    (f"{CPDL}/Ave_verum_corpus_-_William_Byrd/Ave_verum_corpus_-_William_Byrd_page02.png", 4),
    (f"{CPDL}/Ave_verum_corpus_-_William_Byrd/Ave_verum_corpus_-_William_Byrd_page03.png", 4),
    (f"{CPDL}/Ave_verum_corpus_-_William_Byrd/Ave_verum_corpus_-_William_Byrd_page04.png", 4),
    (f"{CPDL}/If_ye_love_me_-_Thomas_Tallis/If_ye_love_me_-_Thomas_Tallis_page01.png", 4),
    (f"{CPDL}/Locus_iste_-_Bruckner/Locus_iste_-_Bruckner_page01.png", 0),  # title page
    (f"{CPDL}/Locus_iste_-_Bruckner/Locus_iste_-_Bruckner_page02.png", 2),  # SA/TB short score
    (f"{CPDL}/Locus_iste_-_Bruckner/Locus_iste_-_Bruckner_page03.png", 2),
    (f"{CPDL}/Sicut_cervus_-_Palestrina/Sicut_cervus_-_Palestrina_page01.png", 4),
    (f"{CPDL}/Sicut_cervus_-_Palestrina/Sicut_cervus_-_Palestrina_page02.png", 4),
    (f"{CPDL}/Sicut_cervus_-_Palestrina/Sicut_cervus_-_Palestrina_page03.png", 4),
    (f"{CPDL}/Sicut_cervus_-_Palestrina/Sicut_cervus_-_Palestrina_page04.png", 4),
    # musicxml.com examples: one-staff, piano and ensemble pages
    (f"{MUSICXML}/Binchois.png", 2),
    (f"{MUSICXML}/Chant.png", 1),
    (f"{MUSICXML}/MozartPianoSonata.png", 2),
    (f"{MUSICXML}/MozartTrio.png", 5),
    (f"{MUSICXML}/Saltarello.png", 1),  # three one-staff systems
    (f"{MUSICXML}/Telemann.png", 3),  # voice + continuo, one one-staff system on top
    # PDMX (MuseScore) SATB scores
    (f"{PDMX}/Qmb5Q3qcB6vQZrDKxUp8kajvLcHVRRxby1tgo7iZBCfzgH_page01.png", 4),
    (f"{PDMX}/Qmb5f7trYCXBdNDqHirQ82fXJ7npCBTWwHasVzWkSQxiMP_page01.png", 4),
    (f"{PDMX}/Qmb6okFHL9g7Hmq7pyercQMePwTHxhiEvYkyKcYH1Z2cK9_page01.png", 4),
    (f"{PDMX}/Qmb6okFHL9g7Hmq7pyercQMePwTHxhiEvYkyKcYH1Z2cK9_page02.png", 4),
    (f"{PDMX}/Qmb6okFHL9g7Hmq7pyercQMePwTHxhiEvYkyKcYH1Z2cK9_page03.png", 4),
    *[(f"{PDMX}/Qmb6tNhkZE96dtGdJG5ApFWcmbMN1Z1xVPNYcZP8KzNG8o_page{n:02d}.png", 6) for n in range(1, 10)],
    (f"{PDMX}/QmbLZoLJ7TzBygbS3Kjzj5bmhtwSy8kAWHKf42BvEXrP2G_page01.png", 4),
    (f"{PDMX}/QmbLZoLJ7TzBygbS3Kjzj5bmhtwSy8kAWHKf42BvEXrP2G_page02.png", 0),  # verses as text
    *[(f"{PDMX}/QmbLrUidn8jvBDG78MVyBKD2oo7EGYfT4NXz2Evcsm6Ww4_page{n:02d}.png", 5) for n in range(1, 7)],
    # SATB + piano with empty staves hidden: systems of 3, 4 and 6 staves
    *[(f"{PDMX}/QmbbjE2QkRM7iptDtFJRhtf64AxhzfpbYdsmRa8zycfUBj_page{n:02d}.png", 6) for n in range(1, 5)],
    (f"{PDMX}/QmbooFzWUHkXfajE6RBDm37NBJgXeNSmPJfSBoGRZUSyJX_page01.png", 0),  # framed cover
    (f"{PDMX}/QmbooFzWUHkXfajE6RBDm37NBJgXeNSmPJfSBoGRZUSyJX_page02.png", 0),  # text and a picture
    (f"{PDMX}/QmbooFzWUHkXfajE6RBDm37NBJgXeNSmPJfSBoGRZUSyJX_page03.png", 7),  # solo + SATB + piano
    (f"{PDMX}/QmbooFzWUHkXfajE6RBDm37NBJgXeNSmPJfSBoGRZUSyJX_page04.png", 0),  # copyright only
    *[(f"{PDMX}/QmbooFzWUHkXfajE6RBDm37NBJgXeNSmPJfSBoGRZUSyJX_page{n:02d}.png", 6) for n in range(5, 11)],
    (f"{PDMX}/QmbooFzWUHkXfajE6RBDm37NBJgXeNSmPJfSBoGRZUSyJX_page11.png", 0),  # back cover text
    *[(f"{PDMX}/QmbtpRoDN7kEeNyUGtsGedpP7Ka3k9QwxS8u5iKTiQJZYm_page{n:02d}.png", 4) for n in range(1, 4)],
    (f"{PDMX}/QmbuvFts9rF2nSfMoUe5yuCEV6pLucrZ1wN2b36WWbFN5J_page01.png", 4),
    (f"{PDMX}/QmbuvFts9rF2nSfMoUe5yuCEV6pLucrZ1wN2b36WWbFN5J_page02.png", 4),
]


@pytest.mark.parametrize(("page", "staves"), EXPECTED, ids=[Path(p).stem for p, _ in EXPECTED])
def test_staves_per_system_on_a_real_page(page, staves):
    path = SAMPLES / page
    if not path.exists():
        pytest.skip(f"sample page not available: {page} (set OMR_TEST_SAMPLES or run the download scripts)")

    assert estimate_staves(path) == staves


def test_every_sample_page_is_in_the_table():
    """A newly downloaded page fails here until someone reads its staves and adds it."""
    if not SAMPLES.exists():
        pytest.skip(f"no samples at {SAMPLES} (set OMR_TEST_SAMPLES or run the download scripts)")
    listed = {page for page, _ in EXPECTED}
    found = {
        str(path.relative_to(SAMPLES))
        for folder in (CPDL, PDMX, MUSICXML)
        for path in (SAMPLES / folder).rglob("*.png")
    }

    assert found - listed == set()
