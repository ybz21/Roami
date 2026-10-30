---
name: presentation_files
description: Inspect and edit PowerPoint PPTX presentations, slide text, formatting, alignment and native editor colors.
---

# Presentation files

Read the source with `read` and `view: document` before editing. The result lists text objects in slide order, recursively including groups. `shapePath` identifies each object through nested shape collections. Empty decorative text frames are listed separately. Use the user's spatial order when specified; otherwise identify the requested text container from its content and document order.

Named colors belong to the intended editor. Use the installed `editorPalette` when that editor applies; ask or inspect the relevant application metadata when it is unavailable. Do not assume another application's RGB names.

Preserve the original input. Use format-aware tools to save a separate requested output; change only the selected properties and retain unrelated objects and formatting. Do not write the inspection JSON over the presentation. Re-read the output with `view: document` and check the requested text, alignment and object scope. Keep the original source hash available to detect concurrent edits.

Document inspection is structural evidence. It does not render slides or establish visual quality; use actual rendering and the saved model capabilities for visual requirements.
