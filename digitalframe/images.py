"""Turn a downloaded photo into playback bytes.

HEIC and HEIF always become JPEG. Other files are re-encoded only when EXIF
orientation or the size bound requires it. A file already inside the limit
keeps its original bytes.
"""

from datetime import datetime
from io import BytesIO

from PIL import ExifTags, Image, ImageOps
from pillow_heif import register_heif_opener


register_heif_opener()


def jpeg_from_heic(data, *, quality=75):
    """Convert one HEIC or HEIF payload to JPEG bytes. Nothing is stored."""
    with Image.open(BytesIO(data)) as image:
        oriented = ImageOps.exif_transpose(image)
        output = oriented if oriented.mode == "RGB" else oriented.convert("RGB")
        buffer = BytesIO()
        try:
            output.save(buffer, format="JPEG", quality=quality, optimize=True)
        finally:
            if output is not oriented:
                output.close()
            if oriented is not image:
                oriented.close()
        return buffer.getvalue()


def taken_stamp(data):
    """Return the camera's capture time as ``YYYY.MM.DD HH:MM``.

    The value is the clock stored in the photo. Files without that clock return None.
    """
    if not isinstance(data, (bytes, bytearray)):
        return None
    try:
        with Image.open(BytesIO(data)) as image:
            raw = _exif_taken(image)
    except Exception:
        return None
    return _format_exif_time(raw)


def _exif_taken(image):
    exif = image.getexif()
    if not exif:
        return None
    ifd = exif.get_ifd(ExifTags.IFD.Exif)
    for tag in (ExifTags.Base.DateTimeOriginal, ExifTags.Base.DateTimeDigitized):
        value = ifd.get(tag)
        if isinstance(value, str) and value.strip():
            return value
    value = exif.get(ExifTags.Base.DateTime)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _format_exif_time(raw):
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.strftime("%Y.%m.%d %H:%M")


def fit_bytes(data, *, max_width, max_height, quality, media_type):
    """Shrink playback bytes so they fit inside the box.

    Bytes that already fit are returned unchanged, including a full-size JPEG
    made from a HEIC photo. Scaling does not enlarge a smaller photo.
    """
    with Image.open(BytesIO(data)) as image:
        oriented = ImageOps.exif_transpose(image)
        try:
            if oriented.width <= max_width and oriented.height <= max_height:
                return data, media_type
            oriented.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            return _encode_memory(oriented, media_type, quality)
        finally:
            if oriented is not image:
                oriented.close()


def _encode_memory(image, media_type, quality):
    buffer = BytesIO()
    if media_type == "image/png":
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), media_type
    if media_type == "image/webp":
        output = image if image.mode in {"RGB", "RGBA"} else image.convert("RGB")
        try:
            output.save(buffer, format="WEBP", quality=quality, method=4)
        finally:
            if output is not image:
                output.close()
        return buffer.getvalue(), media_type
    output = image if image.mode == "RGB" else image.convert("RGB")
    try:
        output.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    finally:
        if output is not image:
            output.close()
    return buffer.getvalue(), "image/jpeg"


def publish_derivative(
        source, destination, *, converted, max_width, max_height,
        other_quality, iphone_quality):
    """Write a derivative and return True. Return False to keep the source bytes."""
    with Image.open(source) as image:
        orientation = image.getexif().get(ExifTags.Base.Orientation, 1)
        swaps = orientation in {5, 6, 7, 8}
        width, height = (image.height, image.width) if swaps else image.size
        if not converted and width <= max_width and height <= max_height:
            return False

        # Shrink before transposition so a JPEG can decode a smaller draft.
        decoder_bounds = (max_height, max_width) if swaps else (max_width, max_height)
        image.thumbnail(decoder_bounds, Image.Resampling.LANCZOS)
        oriented = ImageOps.exif_transpose(image)
        try:
            oriented.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            _save(oriented, destination, converted=converted,
                  other_quality=other_quality, iphone_quality=iphone_quality)
            return True
        finally:
            if oriented is not image:
                oriented.close()


def _save(image, destination, *, converted, other_quality, iphone_quality):
    suffix = destination.suffix.lower()
    if converted or suffix in {".jpg", ".jpeg"}:
        output = image if image.mode == "RGB" else image.convert("RGB")
        try:
            output.save(
                destination, format="JPEG",
                quality=iphone_quality if converted else other_quality,
                optimize=True, progressive=True,
            )
        finally:
            if output is not image:
                output.close()
        return
    if suffix == ".png":
        image.save(destination, format="PNG", optimize=True)
        return
    if suffix == ".webp":
        image.save(destination, format="WEBP", quality=other_quality, method=4)
        return
    raise ValueError("Unsupported cached image format")
