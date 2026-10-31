"""Image publication. Files stay on local disk; HEIC is produced in the test."""

from PIL import Image

from digitalframe.images import publish_derivative
from tests.fakes import heic_bytes, jpeg_bytes, png_bytes


def _publish(source, destination, **overrides):
    values = dict(
        converted=False, max_width=1600, max_height=900,
        other_quality=85, iphone_quality=75,
    )
    values.update(overrides)
    return publish_derivative(source, destination, **values)


def test_a_jpeg_inside_the_limit_is_not_rewritten(tmp_path):
    source = tmp_path / "small.jpg"
    source.write_bytes(jpeg_bytes(320, 180))
    destination = tmp_path / "out.jpg"

    assert _publish(source, destination) is False
    assert not destination.exists()
    assert source.read_bytes() == jpeg_bytes(320, 180)


def test_an_oversized_jpeg_shrinks_without_stretching(tmp_path):
    source = tmp_path / "wide.jpg"
    source.write_bytes(jpeg_bytes(2000, 1000))
    destination = tmp_path / "out.jpg"

    assert _publish(source, destination) is True
    with Image.open(destination) as image:
        assert image.format == "JPEG"
        assert image.size == (1600, 800)


def test_an_oversized_png_stays_png(tmp_path):
    source = tmp_path / "wide.png"
    source.write_bytes(png_bytes(2000, 1000))
    destination = tmp_path / "out.png"

    assert _publish(source, destination) is True
    with Image.open(destination) as image:
        assert image.format == "PNG"
        assert image.size == (1600, 800)


def test_heic_becomes_a_jpeg_and_is_not_enlarged(tmp_path):
    source = tmp_path / "portrait.heic"
    source.write_bytes(heic_bytes())
    destination = tmp_path / "portrait.jpg"

    assert _publish(source, destination, converted=True) is True
    with Image.open(destination) as image:
        assert image.format == "JPEG"
        assert image.size == (8, 6)
