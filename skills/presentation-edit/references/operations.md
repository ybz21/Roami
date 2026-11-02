# Edit requests

Pass JSON through `--request-json` as one argv element, or use `--request changes.json` for a workspace request file. Paths are relative to `--workspace` (absolute paths within it also work). Parent directories must exist. Source and destination must differ. The complete validation schema ships as `scripts/edit-request.schema.json`.

The minimal alignment request and named-color form are shown in [the workflow](../SKILL.md). `expectedSha256` is the source presentation hash returned by inspection, not a shell-output artifact hash.

The `colors` shorthand applies a full slide's list of palette names in geometric order, building the same validated batch internally. It requires an observed source hash and a matching number of names; use the general request for partial or mixed edits.

Slides and position ranks start at 1. Alternatively, copy a specific `shapePath` array from inspection: `"target": {"shapePath": [0, 1]}`. Alignment accepts `left`, `center`, `right`, `justify`. Each operation can replace text, set alignment, set text color, or combine them. Alignment and color cannot each be changed twice on the same object in one batch.

`replaceText` accepts required `old` (nonempty literal string) and `new` (possibly empty), plus optional positive integer `expectedCount` (default 1). The observed object must contain exactly that many nonoverlapping matches across its paragraphs. Matching is case-sensitive, with no regex or normalization. Ordinary runs can share a match; the new text uses the first matched run's formatting. Runs, paragraph properties, links and surrounding text remain in place. Multiple replacements on one object execute in request order, each checked against the preceding result. Text replacement runs before alignment/color in the same operation. A mismatch returns `PRESENTATION_TEXT_MATCH_COUNT_MISMATCH` without publishing any part of the batch.

Newlines, XML-invalid characters, matches in computed fields and spans across fields or unsupported inline nodes are unsupported. Line and paragraph breaks are preserved. `PRESENTATION_TEXT_REPLACEMENT_UNSUPPORTED` publishes nothing; use an editor for those changes. Empty text runs retain their formatting. This edits content without resizing boxes or verifying factual accuracy; render and review after editing. Each `changes` entry reports `replaceText.old`, `replaceText.new` and actual `occurrences`.

For a named text color, use `"color": {"editor": "<observed editorPalette.editor>", "palette": "<observed editorPalette.name>", "name": "<requested color name>"}`. Names are resolved case-insensitively from the installed editor palette; there is no fallback. For an explicit RGB request, use `"color": {"rgb": "#ABCDEF"}` instead. These two color forms cannot be combined.

Successful edit receipts include output `path`, `sha256`, `sourceSha256`, `previousSha256`, `sizeBytes`, `writePublished` and observed `changes`. Reinspect the result; include its path in the final task result so the existing delivery mechanism can collect it. Invalid or conflicting requests publish nothing. A post-publication I/O error returns `writePublished: null` and exit 2; reconcile actual files rather than rerunning blindly.

Install this folder as a complete external Skill bundle through the existing Skills import mechanism, retaining scripts and this reference. A text-only SKILL.md import cannot run its scripts. No PPTX-specific registration in the foundation tool catalog is required.

Large inspection results may appear in the normal shell receipt as `artifactRefs` with a stdout preview. Use the existing `read artifact://ID` operation and its offset/hasMore fields to retrieve the complete text. Keep the source SHA256 distinct from the inspection artifact SHA256; edit requests require the former.
