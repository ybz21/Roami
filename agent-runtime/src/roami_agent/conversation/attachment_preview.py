"""Bound PDF parsing in a credential-free child process."""

import json
import sys


def main():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    except ImportError:
        print(json.dumps({"state": "unavailable"}))
        return
    from roami_agent.conversation.attachments import MAX_UPLOAD_BYTES, Attachments

    try:
        body = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
        _, preview = Attachments.preview(body, "document.pdf")
    except (ValueError, OSError, MemoryError, RecursionError):
        preview = {"state": "unavailable"}
    print(json.dumps(preview, ensure_ascii=False))


if __name__ == "__main__":
    main()
