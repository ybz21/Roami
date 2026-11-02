---
name: market-series-report
description: Analyze daily market price and volume CSVs and prepare an English board presentation with charts and presenter notes. Covers closing-price trends, configurable moving averages, price/volume/return correlations, distributions and drawdown. Use for the reporting stage of combined data-cleaning and presentation requests; its executable pipeline computes the facts, builds the editable PPTX and renders it for review.
---

For a combined data-cleaning and market-presentation request, clean and export the CSV first, then use this executable workflow for the supported analysis, charts and report. Read presentation-design as well when adapting the visual direction. It generates editable text and shapes; charts are images, with their source facts retained. Adapt the output when the user specifies a different slide count or design. Clean and inspect the input first; dates must be explicit strings, selected prices positive and volume nonnegative. Invalid dates, duplicates or nonnumeric fields require an explicit cleaning decision.

When the user also requests a cleaned CSV, keep that delivery separate from selecting analysis fields. If installed, read `skill://tabular-analysis` and its CSV-export reference for the cleaning/export step. Preserve the user's requested source schema, including identifiers/index columns; choosing plotting fields does not authorize dropping export fields. For a source-schema-preserving export, add `--source-schema <original.csv>` to this report command: it checks the cleaned input header against the actual original before creating the report. This script reads the CSV and never cleans or exports it.

Run the complete package from the `packagePath` returned by `read skill://market-series-report`. Python dependencies are declared on the entry script; the task environment also needs fontconfig, LibreOffice and Poppler. Use its Python when those dependencies are already installed, or prepare an isolated `uv run --script` environment while downloads are available.

```bash
python <packagePath>/scripts/report.py --workspace <workspace> --path cleaned.csv --date Date --price Close --volume Volume --matrix Open High Low Adj_Close --destination report
```

Choose actual column names. `--matrix` is optional and adds fields to the price/volume/return correlation matrix. Supply `--price-unit` and `--volume-unit` only when known; otherwise the report says source units. `--title` and `--font` preserve explicit choices. The destination must be new; outputs are `report.pptx`, `presenter-notes.md`, `facts.json` and `review-manifest.json` inside it.

The destination's parent must exist. `--calendar-timezone` defaults to UTC: timezone-aware timestamps are converted to it and naive dates/timestamps are interpreted in it. Use the source's known calendar convention rather than inferring an exchange timezone. `--sessions-per-year` controls the disclosed volatility annualization assumption (default 252).

The facts and copy use the same observed cohorts. Price change is distinct from dividend-inclusive total return; annualization assumes 252 observed sessions per year. Calendar cohorts carry their actual date spans and sample counts. Volume does not establish shareholder composition, float turnover or order-book depth. Higher moments describe distributions; temporal dependence is measured separately without a forecast claim.

The receipt includes the final deck hash and every rendered page path. Rendering is not visual inspection. An image-enabled role must read the actual final-page images before claiming visual review. If this role cannot view images, return the review-manifest path and rendered image paths to the coordinator, with that limitation; do not claim inspection or change model capabilities. Keep review paths in execution details rather than presenting diagnostic images as requested deliverables.

Read back the saved deck and notes, inspect all pages and correct unmet requirements. If the presentation is subsequently edited, regenerate its renders before reviewing it. Return the actual requested file links and upload them when the user's task requires remote delivery. Creating a local report does not prove an upload. Preserve the original CSV. A publication-unknown receipt requires inspecting the destination before any mutation; never overwrite it by rerunning.
