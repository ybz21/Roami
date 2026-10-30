# Edit requests

Pass JSON through `--request-json` as one argv element, or use `--request changes.json` for a workspace request file. Paths are relative to `--workspace` (absolute paths within it also work). Parent directories must exist. Source and destination must differ. The complete validation schema ships as `scripts/edit-request.schema.json`.

```json
{
  "path": "input.pptx",
  "expectedSha256": "<sha256 from inspect>",
  "destination": "updated.pptx",
  "expectedDestinationSha256": null,
  "operations": [
    {
      "slide": 1,
      "target": {"order": "top_to_bottom", "ordinal": 1},
      "alignment": "center"
    }
  ]
}
```

Slides and position ranks start at 1. Alternatively, copy a specific `shapePath` array from inspection: `"target": {"shapePath": [0, 1]}`. Alignment accepts `left`, `center`, `right`, `justify`. Each operation can set alignment, text color, or both. A property cannot be changed twice on the same object in one batch.

For a named text color, use `"color": {"editor": "<observed editorPalette.editor>", "palette": "<observed editorPalette.name>", "name": "<requested color name>"}`. Names are resolved case-insensitively from the installed editor palette; there is no fallback. For an explicit RGB request, use `"color": {"rgb": "#ABCDEF"}` instead. These two color forms cannot be combined.

Successful edit receipts include output `path`, `sha256`, `sourceSha256`, `previousSha256`, `sizeBytes`, `writePublished` and observed `changes`. Reinspect the result; include its path in the final task result so the existing delivery mechanism can collect it. Invalid or conflicting requests publish nothing. A post-publication I/O error returns `writePublished: null` and exit 2; reconcile actual files rather than rerunning blindly.

Install this folder as a complete external Skill bundle through the existing Skills import mechanism, retaining scripts and this reference. A text-only SKILL.md import cannot run its scripts. No PPTX-specific registration in the foundation tool catalog is required.

Large inspection results may appear in the normal shell receipt as `artifactRefs` with a stdout preview. Use the existing `read artifact://ID` operation and its offset/hasMore fields to retrieve the complete text. Keep the source SHA256 distinct from the inspection artifact SHA256; edit requests require the former.
