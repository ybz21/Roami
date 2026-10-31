---
name: tabular-analysis
description: Inspect CSV snapshots and publish cleaned source-schema exports with keyed recovery of source identifiers, explicit numeric normalization, and guarded file writes. Use for CSV cleaning alongside analyses, charts, or reports so derived analysis fields do not silently change the cleaned export.
---

Use the bundled export command for a cleaned CSV copy. It projects the source column names and order, excludes analysis-only fields, and can recover omitted source columns through explicit keys. Decide the task-specific cleaning and analysis separately; this command does not choose invalid rows or analytical methods. Keep source identifiers by default, including unnamed columns; use `--columns` only for a different schema explicitly requested by the user.

Read this Skill's `packagePath` from the tool result. The scripts use Python's standard library and need no package installation.

```sh
python <packagePath>/scripts/csv_export.py inspect --workspace <directory> --path raw.csv
python <packagePath>/scripts/csv_export.py inspect --workspace <directory> --path analysis.csv
python <packagePath>/scripts/csv_export.py export --workspace <directory> \
  --source raw.csv --analysis analysis.csv --destination cleaned.csv \
  --expected-source-sha256 <observed-source-sha> \
  --expected-analysis-sha256 <observed-analysis-sha> \
  --keys event_date --date-keys event_date --values source --numeric units value
```

For cleaning that only filters or reorders rows, `--values source` retains the matching original field values and representations, including timestamp/time-zone text. For corrections or imputation, use the default `--values analysis` to retain edited values; source mode would undo those edits.

Choose keys from the actual input, not the example. Source rows matching those keys must be unique; ambiguous or unmatched keys stop publication. `--date-keys` explicitly compares ISO civil dates, allowing a timestamp to match its date-only form. It preserves the matched source date-key text even in analysis-value mode; use `--analysis-key-values` only when the user requests that format change. It does not infer time zones; use full or prepared keys when time-of-day matters. A collision is an error, not permission to pick a row.

Choose `--numeric` only for fields established as numeric by the input and task. It validates finite numbers and removes incidental decimal-zero suffixes from ordinary integral representations; it does not round fractional data or convert undeclared identifier fields. Preserve full input precision during analysis and format chart labels separately.

The source and analysis files remain unchanged. The output is separate and create-only by default; replacing an existing output requires its observed `--expected-destination-sha256`. Input changes fail before publication. If a failure reports `writePublished: true`, inspect the output and reconcile its hash before considering another write.

Inspect the exported CSV and use it for the requested cleaned-data delivery, keeping derived features in the analysis data unless requested as output. When the destination is a service, use the task's authorized transfer interface and confirm remote delivery. Reopen requested charts or reports and state any unverified visual limitations.
