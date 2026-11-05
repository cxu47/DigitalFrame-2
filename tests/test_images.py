"""Image publication. Files stay on local disk; HEIC is produced in the test."""

from io import BytesIO

from PIL import ExifTags, Image

from digitalframe.images import fit_bytes, publish_derivative, taken_stamp
from tests.fakes import heic_bytes, jpeg_bytes, png_bytes


def _publish(source, destination, **overrides):
    values = dict(
        converted=False, max_width=1600, max_height=900,
        other_quality=85, iphone_quality=75,
    )
    values.update(overrides)
    return publish_derivative(source, destination, **values)


def _jpeg_taken_at(when):
    image = Image.new("RGB", (16, 10), (8, 9, 10))
    exif = Image.Exif()
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = when
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_taken_stamp_reads_the_camera_clock():
    assert taken_stamp(_jpeg_taken_at("2024:09:12 14:30:45")) == "2024.09.12 14:30"
    assert taken_stamp(jpeg_bytes(20, 10)) is None
    assert taken_stamp(b"not-a-photo") is None


def test_fit_bytes_keeps_a_photo_that_is_already_inside_the_box():
    original = jpeg_bytes(320, 180)
    data, media_type = fit_bytes(
        original, max_width=1600, max_height=900, quality=85, media_type="image/jpeg")
    assert data == original
    assert media_type == "image/jpeg"


def test_fit_bytes_shrinks_a_wide_photo_without_stretching():
    data, media_type = fit_bytes(
        jpeg_bytes(2000, 1000), max_width=1600, max_height=900,
        quality=85, media_type="image/jpeg")
    assert media_type == "image/jpeg"
    with Image.open(BytesIO(data)) as image:
        assert image.size == (1600, 800)


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
