import io

import pytest
from PIL import Image

from roami_agent.context.image_preparation import encoded_size, prepare_image
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.image_limits import MAX_PIXELS, ImageLimits
from roami_agent.server.configuration import Settings


def picture(mode="RGB", size=(60, 40), color="white", format="PNG", **options):
    image = Image.new(mode, size, color)
    output = io.BytesIO()
    image.save(output, format, **options)
    return output.getvalue()


def test_compliant_png_is_preserved_byte_for_byte_with_transparency():
    body = picture("RGBA", color=(10, 20, 30, 50))
    result = prepare_image(body)
    assert result["body"] is body
    assert result["mimeType"] == "image/png" and not result["optimized"]
    with Image.open(io.BytesIO(result["body"])) as image:
        assert image.getpixel((0, 0)) == (10, 20, 30, 50)


def test_large_screenshot_keeps_png_alpha_and_aspect_ratio():
    result = prepare_image(picture("RGBA", (3000, 1200), (0, 0, 0, 0)))
    assert (result["width"], result["height"]) == (2000, 800)
    assert result["originalWidth"] == 3000 and result["optimized"]
    assert result["mimeType"] == "image/png"
    with Image.open(io.BytesIO(result["body"])) as image:
        assert image.getpixel((0, 0))[3] == 0


def test_model_encoded_limit_uses_base64_size_and_jpeg_fallback():
    body = Image.effect_noise((1000, 700), 80).convert("RGB")
    output = io.BytesIO()
    body.save(output, "PNG")
    result = prepare_image(output.getvalue(), ImageLimits(max_encoded_bytes=100000))
    assert result["mimeType"] == "image/jpeg"
    assert encoded_size(result["body"]) <= 100000
    assert result["width"] <= 1000 and result["height"] <= 700


def test_stricter_model_dimensions_and_very_small_payload_progressively_resize():
    result = prepare_image(
        picture(size=(1000, 500)), ImageLimits(max_width=100, max_height=100, max_encoded_bytes=150)
    )
    assert result["width"] <= 100 and result["height"] <= 50
    assert encoded_size(result["body"]) <= 150


def test_exif_orientation_is_applied_and_not_sent_twice():
    exif = Image.Exif()
    exif[274] = 6
    result = prepare_image(picture(size=(90, 40), format="JPEG", exif=exif))
    assert (result["width"], result["height"]) == (40, 90)
    with Image.open(io.BytesIO(result["body"])) as image:
        assert image.getexif().get(274, 1) == 1


def test_impossible_payload_is_an_explicit_failure():
    with pytest.raises(ValueError, match="IMAGE_ENCODED_LIMIT"):
        prepare_image(picture(), ImageLimits(max_encoded_bytes=1))


@pytest.mark.parametrize(
    "value",
    [{"max_width": True}, {"jpeg_quality": 0}, {"max_encoded_bytes": "123"}, {"unknown": 1}],
)
def test_invalid_model_image_limits(value):
    with pytest.raises(DomainError, match="INVALID_MODEL_IMAGE_LIMITS"):
        ImageLimits.configured(value)


def test_role_specific_limits_load_without_changing_model_token_capacity(tmp_path):
    config = tmp_path / "agent.toml"
    config.write_text(
        '[model]\nendpoint="https://fixture.example/v1"\nname="main"\ncontext_window=1000000\n[model.image_limits]\nmax_width=1200\n[worker.model]\nname="worker"\n[worker.model.image_limits]\nmax_encoded_bytes=100000\n'
    )
    settings = Settings.load(config)
    assert ImageLimits.configured(settings.route().image_limits).max_width == 1200
    assert ImageLimits.configured(settings.route("worker").image_limits).max_encoded_bytes == 100000
    assert settings.compaction_threshold == 750000
    assert MAX_PIXELS == 64000000


def test_transparent_jpeg_fallback_is_white_not_black():
    image = Image.effect_noise((200, 200), 80).convert("RGBA")
    image.putalpha(0)
    output = io.BytesIO()
    image.save(output, "PNG")
    result = prepare_image(output.getvalue(), ImageLimits(max_encoded_bytes=2000))
    assert result["mimeType"] == "image/jpeg"
    with Image.open(io.BytesIO(result["body"])) as rendered:
        assert min(rendered.getpixel((0, 0))) >= 250
