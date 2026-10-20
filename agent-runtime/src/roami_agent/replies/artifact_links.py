"""Keep task handoffs linked to their persisted deliverables."""

import re
from urllib.parse import parse_qs, urlsplit

LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\n]+)\)")
ARTIFACT_URL = re.compile(r"/api/agent/artifacts/[^/]+/content")
BARE_ARTIFACT_URL = re.compile(r"(?<![\w/])(/api/agent/artifacts/[^/\s)\"'<>]+/content)(?![\w/])")


def deliverable_links(text, references):
    if not references:
        return text
    urls = {"/api/agent/artifacts/" + item["id"] + "/content" for item in references}
    names = {}
    for item in references:
        names.setdefault(item["name"], []).append("/api/agent/artifacts/" + item["id"] + "/content")

    def replace(match):
        label, url = match.groups()
        if url.startswith("/api/file/raw?"):
            url = parse_qs(urlsplit(url).query).get("path", [""])[0]
        if not ARTIFACT_URL.fullmatch(url):
            return match[0]
        if url in urls:
            return f"[{label}]({url})"
        candidates = names.get(label, [])
        # A unique persisted filename binds a copied URL; ambiguous names stay unlinked.
        return f"[{label}]({candidates[0]})" if len(candidates) == 1 else label

    text = LINK.sub(replace, text)
    linked = {match[2] for match in LINK.finditer(text)}
    linked.update(match[1] for match in BARE_ARTIFACT_URL.finditer(text))
    missing = []
    for item in references:
        url = "/api/agent/artifacts/" + item["id"] + "/content"
        if url not in linked:
            name = item["name"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            missing.append(f"[{name}]({url})")
    return text.rstrip() + ("\n\n" + "\n".join(missing) if missing else "")
