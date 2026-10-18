"""Fit image dimensions and encoded payload while retaining readable source formats."""

import io

from PIL import Image, ImageOps

from roami_agent.protocol.image_limits import MAX_PIXELS, ImageLimits


def encoded_size(body):
    return ((len(body) + 2) // 3) * 4


def encoded_candidates(image, jpeg_quality):
    output = io.BytesIO()
    image.save(output, format="PNG")
    yield output.getvalue(), "image/png"
    rgba = image.convert("RGBA")
    rgb = Image.new("RGB", image.size, "white")
    rgb.paste(rgba, mask=rgba.getchannel("A"))
    for quality in dict.fromkeys([jpeg_quality, 70, 55, 40]):
        output = io.BytesIO()
        rgb.save(output, format="JPEG", quality=min(quality, jpeg_quality))
        yield output.getvalue(), "image/jpeg"


def prepare_image(body, limits=None):
    limits = limits or ImageLimits()
    with Image.open(io.BytesIO(body)) as original:
        if original.width * original.height > MAX_PIXELS or original.format not in {
            "PNG",
            "JPEG",
            "WEBP",
        }:
            raise ValueError("IMAGE_INPUT_LIMIT")
        original_width, original_height = original.size
        orientation = original.getexif().get(274, 1)
        if (
            orientation == 1
            and original.width <= limits.max_width
            and original.height <= limits.max_height
            and encoded_size(body) <= limits.max_encoded_bytes
        ):
            return {
                "body": body,
                "mimeType": Image.MIME[original.format],
                "width": original.width,
                "height": original.height,
                "originalWidth": original_width,
                "originalHeight": original_height,
                "optimized": False,
            }
        image = ImageOps.exif_transpose(original) if orientation != 1 else original
        image.thumbnail((limits.max_width, limits.max_height), Image.Resampling.LANCZOS)
        while True:
            for candidate, mime in encoded_candidates(image, limits.jpeg_quality):
                if encoded_size(candidate) <= limits.max_encoded_bytes:
                    return {
                        "body": candidate,
                        "mimeType": mime,
                        "width": image.width,
                        "height": image.height,
                        "originalWidth": original_width,
                        "originalHeight": original_height,
                        "optimized": True,
                    }
            if image.size == (1, 1):
                raise ValueError("IMAGE_ENCODED_LIMIT")
            image = image.resize(
                (max(1, int(image.width * 0.75)), max(1, int(image.height * 0.75))),
                Image.Resampling.LANCZOS,
            )
