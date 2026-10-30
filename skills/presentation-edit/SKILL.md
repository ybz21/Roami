---
name: presentation-edit
description: Inspect and edit existing PPTX slide text alignment and colors while preserving editable objects and unrelated document parts. Use for PowerPoint or Impress file changes (演示文稿、幻灯片).
---

# Presentation editing

This optional package supplies the document logic and dependencies. Run its script through the normal shell capability; it adds no Agent tool or model configuration. Import the complete Skill package or place it under a configured local Skill root. Then `read skill://presentation-edit` returns `packagePath`. Local packages run from their configured directory; imported packages run from their retained snapshot.

Use Python 3.12+ with the dependencies declared in the script metadata (`lxml` and `jsonschema`). When the task environment already provides them, invoke its Python directly as below. Otherwise prepare a separate environment with `uv run --script <packagePath>/scripts/presentation.py --help` while dependencies can be downloaded, then use `uv run --offline --script` instead of `python`. An empty uv cache cannot resolve dependencies offline even when the task's Python already has them.

Inspect the source before choosing objects:

```bash
python <packagePath>/scripts/presentation.py inspect --workspace <workspace> --path input.pptx
```

Use the observed `shapePath` for a specific text frame. `drawingOrdinal` identifies drawing traversal; `topToBottomRank` and `topToBottomPaths` describe geometric top-to-bottom order. These are different facts: a bottom caption can be drawn first. Unknown or overlapping placement needs inspection in the actual editor or a rendering. Structural inspection alone does not establish visual quality.

If the shell externalizes a long inspection result, read its returned text artifact through `read artifact://ID` and follow the returned page offsets. A stdout preview is not the complete JSON document; do not infer missing objects from it.

For supported alignment or color changes, use the bundled edit command after inspection. It handles object selection and source/destination checks. A minimal request is:

```json
{
  "path": "input.pptx",
  "expectedSha256": "<source sha256 from inspect>",
  "destination": "updated.pptx",
  "expectedDestinationSha256": null,
  "operations": [
    {"slide": 1, "target": {"order": "top_to_bottom", "ordinal": 1}, "alignment": "center"}
  ]
}
```

Use the requested slide, object and alignment; add operations for additional changes. For a specific observed object use `"target": {"shapePath": [0, 1]}` instead of a rank. For a named color, add `"color": {"editor": "<observed editorPalette.editor>", "palette": "<observed editorPalette.name>", "name": "<requested color>"}`. Detailed validation and receipt fields are in [the request reference](references/operations.md).

Run the complete request as one batch:

```bash
python <packagePath>/scripts/presentation.py edit --workspace <workspace> --request-json '<request JSON>'
```

Preserve the original input. Source and destination hashes must match the observations; null means create a new destination. The script validates the full batch before publishing a separate editable PPTX. For a named color use the observed editor, palette and requested color name; an RGB value is appropriate when explicitly specified. Unknown names never fall back to guessed RGB values.

Pass the JSON as one shell argv element. For a large batch, `--request changes.json` can read a request file inside the workspace instead. Keep request files and diagnostic logs out of user deliverables.

Inspect the saved output and verify the requested changes and object scope. Return the output path as a usable file link in the task result, with verified changes and any unmet requirements. A shell success or file hash does not prove the user's full task passed. If the receipt says publication is unknown, inspect the existing source/destination before any further mutation.

Other presentation operations can use suitable offline editors or scripts; this package currently edits alignment and text color only. It does not select models, call a provider, impose token/spending limits or modify the Agent runtime. Dependencies are declared on the script and resolved by `uv` outside the core environment.
