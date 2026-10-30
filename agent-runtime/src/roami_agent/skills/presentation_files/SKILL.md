---
name: presentation_files
description: Inspect and edit PowerPoint PPTX presentations, slide text, formatting, alignment and native editor colors.
---

# Presentation files

Read the source with `read` and `view: document` before editing. `shapePath` identifies each object through nested shape collections; `ordinal` is drawing traversal, not reading order. Empty decorative text frames are listed separately.

Locate the requested text container from its content and placement. Do not select a "first textbox" by drawing ordinal alone. `slideBounds` gives explicit shape bounds in slide EMU coordinates, including group scaling, rotation and flips. `topToBottomPaths` sorts nonempty text frames by top edge, then left edge; it is null when any position is unresolved. Respect the user's requested order. Bounds do not establish visibility or reading order for overlapping objects. Inspect the native application or a rendering when inherited or ambiguous layout prevents identifying the intended object.

Named colors belong to the intended editor. Use the installed `editorPalette` when that editor applies; ask or inspect the relevant application metadata when it is unavailable. Do not assume another application's RGB names.

Preserve the original input. Use format-aware tools to save a separate requested output; change only the selected properties and retain unrelated objects and formatting. Do not write the inspection JSON over the presentation. Re-read the output with `view: document` and check the requested text, alignment and object scope. Keep the original source hash available to detect concurrent edits.

Document inspection is structural evidence. It does not render slides or establish visual quality; use actual rendering and the saved model capabilities for visual requirements.
