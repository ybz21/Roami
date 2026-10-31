---
name: presentation-edit
description: Edit existing PPTX textbox alignment and named text colors while preserving editable objects. Use before PowerPoint/Impress alignment or color changes (演示文稿、幻灯片); resolves visible textbox order and the installed editor's named palette instead of assuming drawing order or guessing RGB values.
---

# Presentation editing

This optional package supplies the document logic and dependencies. Run its script through the normal shell capability; it adds no Agent tool or model configuration. Import the complete Skill package or place it under a configured local Skill root. Then `read skill://presentation-edit` returns `packagePath`. Local packages run from their configured directory; imported packages run from their retained snapshot.

Use Python 3.12+ with the dependencies declared in the script metadata (`lxml` and `jsonschema`). When the task environment already provides them, invoke its Python directly as below. Otherwise prepare a separate environment with `uv run --script <packagePath>/scripts/presentation.py --help` while dependencies can be downloaded, then use `uv run --offline --script` instead of `python`. An empty uv cache cannot resolve dependencies offline even when the task's Python already has them.

Inspect the source before choosing objects:

```bash
python <packagePath>/scripts/presentation.py inspect --workspace <workspace> --path input.pptx --slide <requested-slide-number>
```

Use `--slide` for a slide-specific task so the requested objects and palette fit in the inspection result; omit it only when the task needs the entire deck.

Use the observed `shapePath` for a specific text frame. `drawingOrdinal` identifies drawing traversal; `topToBottomRank` and `topToBottomPaths` describe geometric top-to-bottom order. These are different facts: a bottom caption can be drawn first. Unknown or overlapping placement needs inspection in the actual editor or a rendering. Structural inspection alone does not establish visual quality.

For ordinal references to visible textboxes, such as the first or second textbox, use unambiguous geometric top-to-bottom order unless the user specifies drawing or tab order. Do not substitute a drawing ordinal for visible order. If the requested object is still ambiguous, report that uncertainty instead of claiming the selection was verified.

If the shell externalizes a long inspection result, read its returned text artifact through `read artifact://ID` and follow the returned page offsets. A stdout preview is not the complete JSON document; do not infer missing objects from it.

For a slide's full list of named text colors, use the names-only command below. Keep every requested color as a name; do not translate one of them to a guessed RGB literal or mix guessed RGB with named colors in a batch. It maps the nonempty textboxes in geometric top-to-bottom order and resolves names from the installed editor's palette, avoiding a manual RGB translation:

```bash
python <packagePath>/scripts/presentation.py colors --workspace <workspace> --path input.pptx --destination updated.pptx --expected-sha256 <source-sha256> --slide 1 --names Blue Orange Purple
```

Replace the slide and names with the user's request. The name count must equal that slide's nonempty textbox count. Unknown colors, ambiguous placement or changed input publish nothing. The destination must be new; to revise an observed existing output, also pass `--expected-destination-sha256 <output-sha256>`. For a subset of objects, mixed changes or an explicit RGB request, use the batch edit form below.

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
