---
name: tabular-analysis
description: Inspect CSV snapshots, compare chosen summary statistics with source hashes, and publish cleaned source-schema exports with explicit numeric normalization and guarded writes. Use for CSV cleaning and data-backed charts or reports; derived analysis fields stay separate from the cleaned export.
---

Choose the workflow for the requested output. Read its linked instructions before the covered operations; several workflows may apply to one task. Use the supported scripts from the `packagePath` returned by `skill_read`. They use Python's standard library and need no package installation.

| Requested work | Instructions and command |
| --- | --- |
| Clean or publish a CSV | [CSV export](references/csv-export.md): `scripts/csv_export.py inspect` then `export`; preserve source columns and keep derived analysis fields separate. |
| Summarize a distribution or identify dated extremes | [Descriptive statistics](references/descriptive-statistics.md): `scripts/numeric_profile.py`; choose the actual fields, transform and record labels. |
| Compare periods, groups, levels or changes in a report | [Numeric comparisons](references/numeric-comparisons.md): `scripts/numeric_comparison.py`; prepare the actual cohorts and explicitly choose the statistic. |
| Interpret price and volume evidence | [Market data evidence](references/market-data-evidence.md): distinguish descriptive associations from forecasts, causes and liquidity claims. |

For numerical reports, build conclusions from the relevant receipts. Keep the statistic, periods, units and computed values consistent across charts, visible text, notes and the presenter script; do not estimate a percentage or a phrase such as "halved" from memory. Read and check the final requested artifacts, not just the analysis code. Reports still need task-specific analysis and visual review beyond what these scripts establish.
