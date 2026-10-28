"""The source preview: a downscaled JPEG in the output root, handed out by opaque job id."""

import pytest
from PIL import Image
from sheet_music_mcp_core.artifacts import InMemoryArtifactStore
from sheet_music_mcp_core.errors import ProcessingError

from omr_mcp.previews import MAX_PREVIEW_SIDE, SourcePreviews, write_source_preview


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SHEET_MUSIC_OUTPUT_ROOT", str(tmp_path / "out"))
    return tmp_path / "out"


def _image(tmp_path, size, mode="RGB", name="in.png"):
    path = tmp_path / name
    Image.new(mode, size, "white").save(path)
    return path


class TestWriteSourcePreview:
    def test_a_large_image_is_scaled_to_the_limit(self, tmp_path, output_root):
        preview = write_source_preview(_image(tmp_path, (3200, 2400)))

        with Image.open(preview) as jpeg:
            assert jpeg.format == "JPEG"
            assert max(jpeg.size) == MAX_PREVIEW_SIDE
            assert jpeg.size == (1600, 1200)
        assert preview.resolve().is_relative_to(output_root.resolve())

    def test_a_small_image_is_not_enlarged(self, tmp_path):
        with Image.open(write_source_preview(_image(tmp_path, (300, 200)))) as jpeg:
            assert jpeg.size == (300, 200)

    @pytest.mark.parametrize("mode", ["RGBA", "L", "P", "1"])
    def test_every_mode_becomes_a_jpeg(self, tmp_path, mode):
        with Image.open(write_source_preview(_image(tmp_path, (50, 50), mode))) as jpeg:
            assert jpeg.format == "JPEG"

    def test_transparency_becomes_white_not_black(self, tmp_path):
        path = tmp_path / "t.png"
        Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(path)

        with Image.open(write_source_preview(path)) as jpeg:
            assert jpeg.getpixel((5, 5))[0] > 240

    def test_the_source_is_left_alone(self, tmp_path):
        path = _image(tmp_path, (3200, 100))
        before = path.read_bytes()

        write_source_preview(path)

        assert path.read_bytes() == before

    def test_an_unreadable_image_raises(self, tmp_path):
        path = tmp_path / "bad.png"
        path.write_bytes(b"x")

        with pytest.raises(ProcessingError):
            write_source_preview(path)


class TestSourcePreviews:
    def test_a_job_maps_each_page_to_its_artifact(self, tmp_path):
        previews, store = SourcePreviews(), InMemoryArtifactStore()
        pages = [write_source_preview(_image(tmp_path, (10, 10), name=f"{i}.png")) for i in range(2)]

        job_id = previews.register(store, pages)

        first, second = previews.artifact_id(job_id, 1), previews.artifact_id(job_id, 2)
        assert first != second
        assert store.info(first).kind == "image/jpeg"

    def test_a_page_without_a_preview_is_not_available(self, tmp_path):
        previews, store = SourcePreviews(), InMemoryArtifactStore()
        job_id = previews.register(store, [None, write_source_preview(_image(tmp_path, (10, 10)))])

        assert previews.available_pages(job_id) == [False, True]
        with pytest.raises(ProcessingError) as excinfo:
            previews.artifact_id(job_id, 1)
        assert excinfo.value.error_code == "INVALID_PARAMETER"

    @pytest.mark.parametrize("job_id", ["nope", "", "../../etc/passwd", "/etc/passwd", None, 5])
    def test_an_unknown_job_is_invalid_parameter_and_never_a_path(self, job_id):
        with pytest.raises(ProcessingError) as excinfo:
            SourcePreviews().artifact_id(job_id, 1)

        assert excinfo.value.error_code == "INVALID_PARAMETER"

    @pytest.mark.parametrize("page", [0, 3, -1, True, "1", 1.5])
    def test_a_page_outside_the_job_is_invalid_parameter(self, tmp_path, page):
        previews, store = SourcePreviews(), InMemoryArtifactStore()
        job_id = previews.register(store, [write_source_preview(_image(tmp_path, (10, 10)))])

        with pytest.raises(ProcessingError) as excinfo:
            previews.artifact_id(job_id, page)

        assert excinfo.value.error_code == "INVALID_PARAMETER"

    def test_old_jobs_are_forgotten(self, tmp_path):
        previews, store = SourcePreviews(max_jobs=2), InMemoryArtifactStore()
        jobs = [previews.register(store, [write_source_preview(_image(tmp_path, (10, 10)))]) for _ in range(3)]

        with pytest.raises(ProcessingError):
            previews.artifact_id(jobs[0], 1)
        assert previews.artifact_id(jobs[2], 1)
