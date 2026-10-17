import time
import uuid


def identity() -> str:
    return uuid.uuid4().hex


def now_ms() -> int:
    return time.time_ns() // 1_000_000
