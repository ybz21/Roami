"""Keep task handoffs linked to their persisted deliverables."""

import ipaddress
import json
import re
from urllib.parse import parse_qs, urlsplit

LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\n]+)\)")
ARTIFACT_URL = re.compile(r"/api/agent/artifacts/[^/]+/content")
URL_TOKEN = re.compile(
    LINK.pattern
    + r"|(?:https?://|//)[^\s)\"'<>]+|(?<![\w/])/api/agent/artifacts/[^/\s)\"'<>]+/content(?![\w/])",
    re.IGNORECASE,
)


def artifact_path(url):
    try:
        parsed = urlsplit(url)
        if parsed.netloc:
            host = (parsed.hostname or "").rstrip(".").lower()
            if host != "localhost":
                try:
                    if not ipaddress.ip_address(host).is_loopback:
                        return None
                except ValueError:
                    return None
        elif not url.startswith("/"):
            return None
        path = parsed.path
        if path == "/api/file/raw":
            path = parse_qs(parsed.query).get("path", [""])[0]
        return path if ARTIFACT_URL.fullmatch(path) else None
    except ValueError:
        return None


def link_label(name):
    return name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def deliverable_links(text, references):
    if not references:
        return text
    urls = {"/api/agent/artifacts/" + item["id"] + "/content" for item in references}
    names = {}
    for item in references:
        names.setdefault(item["name"], []).append("/api/agent/artifacts/" + item["id"] + "/content")

    try:
        json.loads(text)
        structured = True
    except (ValueError, TypeError):
        structured = False
    labels = {
        "/api/agent/artifacts/" + item["id"] + "/content": item["name"] for item in references
    }

    def replace(match):
        label, url = match.groups()
        path = artifact_path(url)
        if path is None:
            return match[0]
        url = path
        if url in urls:
            return f"[{label}]({url})"
        candidates = names.get(label, [])
        # A unique persisted filename binds a copied URL; ambiguous names stay unlinked.
        return f"[{label}]({candidates[0]})" if len(candidates) == 1 else label

    text = LINK.sub(replace, text)

    def replace_bare(match):
        raw = match[0]
        if LINK.fullmatch(raw):
            return raw
        url = raw.rstrip(".,;!?:，。；！？")
        suffix = raw[len(url) :]
        path = artifact_path(url)
        if path is None:
            return raw
        if path not in urls:
            return suffix
        if not structured:
            return f"[{link_label(labels[path])}]({path})" + suffix
        return path + suffix

    text = URL_TOKEN.sub(replace_bare, text)
    linked = {match[2] for match in LINK.finditer(text) if match[2] in urls}
    linked.update(match[0] for match in URL_TOKEN.finditer(text) if match[0] in urls)
    missing = []
    for item in references:
        url = "/api/agent/artifacts/" + item["id"] + "/content"
        if url not in linked:
            name = link_label(item["name"])
            missing.append(f"[{name}]({url})")
    return text.rstrip() + ("\n\n" + "\n".join(missing) if missing else "")
