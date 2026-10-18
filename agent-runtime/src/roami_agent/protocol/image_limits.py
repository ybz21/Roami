"""Role-specific limits for inline image inputs."""

from dataclasses import dataclass, fields

from roami_agent.protocol.errors import DomainError

MAX_PIXELS = 64_000_000


@dataclass(frozen=True)
class ImageLimits:
    max_width: int = 2000
    max_height: int = 2000
    max_encoded_bytes: int = 4_718_592
    jpeg_quality: int = 80

    @classmethod
    def configured(cls, value):
        if not isinstance(value, dict) or set(value) - {f.name for f in fields(cls)}:
            raise DomainError("INVALID_MODEL_IMAGE_LIMITS")
        limits = cls(**value)
        for name, maximum in [
            ("max_width", 16384),
            ("max_height", 16384),
            ("max_encoded_bytes", 20 * 1024 * 1024),
            ("jpeg_quality", 95),
        ]:
            number = getattr(limits, name)
            if type(number) is not int or not 1 <= number <= maximum:
                raise DomainError("INVALID_MODEL_IMAGE_LIMITS")
        return limits
