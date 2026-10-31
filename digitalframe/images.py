"""Turn a downloaded photo into playback bytes.

HEIC and HEIF always become JPEG. Other files are re-encoded only when EXIF
orientation or the size bound requires it. A file already inside the limit
keeps its original bytes.
"""

from PIL import ExifTags, Image, ImageOps
from pillow_heif import register_heif_opener


register_heif_opener()


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
