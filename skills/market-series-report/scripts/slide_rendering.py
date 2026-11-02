"""Confirm the font and render the saved deck without changing its bytes."""

import hashlib
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def font_family(requested):
    for name in (
        [requested] if requested else ["Liberation Sans", "Carlito", "DejaVu Sans"]
    ):
        run = subprocess.run(
            ["fc-match", "-f", "%{family}", name],
            capture_output=True,
            text=True,
            check=True,
        )
        actual = run.stdout.strip().split(",")[0]
        if actual.casefold() == name.casefold():
            return name
    raise ValueError("REQUESTED_FONT_UNAVAILABLE")


def render(folder, slides):
    if not all(shutil.which(name) for name in ["soffice", "pdftoppm"]):
        raise ValueError("LIBREOFFICE_AND_POPPLER_REQUIRED")
    source = folder / "report.pptx"
    before = digest(source)
    output = folder / "review"
    output.mkdir()
    profile = folder / "office-profile"
    subprocess.run(
        [
            "soffice",
            "-env:UserInstallation=" + profile.as_uri(),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output),
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            "105",
            "-png",
            str(output / "report.pdf"),
            str(output / "page"),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    pages = sorted(
        output.glob("page-*.png"), key=lambda path: int(path.stem.split("-")[-1])
    )
    if len(pages) != slides or digest(source) != before:
        raise ValueError("RENDER_SOURCE_OR_PAGE_COUNT_CHANGED")
    shutil.rmtree(profile)
    return {
        "deckSha256": before,
        "pageCount": len(pages),
        "pages": [
            {"path": str(path.relative_to(folder)), "sha256": digest(path)}
            for path in pages
        ],
        "visualInspectionPerformed": False,
    }
