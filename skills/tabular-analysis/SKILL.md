---
name: tabular-analysis
description: Inspect CSV snapshots and publish cleaned source-schema exports with keyed recovery of source identifiers, explicit numeric normalization, and guarded file writes. Use for CSV cleaning alongside analyses, charts, or reports so derived analysis fields do not silently change the cleaned export.
---

Use the bundled export command for a cleaned CSV copy. It projects the source column names and order, excludes analysis-only fields, and can recover omitted source columns through explicit keys. Decide the task-specific cleaning and analysis separately; this command does not choose invalid rows or analytical methods. Keep source identifiers by default, including unnamed columns; use `--columns` only for a different schema explicitly requested by the user.

Read this Skill's `packagePath` from the tool result. The scripts use Python's standard library and need no package installation.

Use the original downloaded input as `source`, before any normalization or rounding; a cleaned intermediate table is `analysis`, not a replacement source. Inspect both snapshots, then write the export choices as a JSON file. Arrays keep each full column name intact even when names contain spaces, quotes, Unicode or shell characters.

```sh
python <packagePath>/scripts/csv_export.py inspect --workspace <directory> --path raw.csv
python <packagePath>/scripts/csv_export.py inspect --workspace <directory> --path analysis.csv
```

Write `export.json` using the actual columns and the two observed hashes:

```json
{
  "source": "raw.csv",
  "analysis": "analysis.csv",
  "destination": "cleaned.csv",
  "expectedSourceSha256": "<observed-source-sha>",
  "expectedAnalysisSha256": "<observed-analysis-sha>",
  "keys": ["event date"],
  "dateKeys": ["event date"],
  "values": "source",
  "numeric": ["units", "total amount"]
}
```

```sh
python <packagePath>/scripts/csv_export.py export --workspace <directory> --spec export.json
```

`numeric` is required in a spec: list the fields whose numeric representations should be normalized, or explicitly use `[]` if none. Omitting it is rejected, so a forgotten selection cannot silently skip the decision. The spec accepts the same options as individual flags: `columns`, `analysisKeyValues`, and `expectedDestinationSha256` are optional. Do not mix `--spec` with individual export options. For direct flags, use structured `bash.argv` items for full field names. If field selection fails, use the returned rejected names and available columns to repair quoting or the JSON; do not drop intended conversions just to clear an error.

For cleaning that only filters/reorders rows or normalizes selected numeric representations, `values: "source"` (`--values source`) retains the matching original field values and representations, including timestamp/time-zone text. The selected `numeric` conversions still run in source mode; type cleanup alone does not require analysis mode. For actual cell-value corrections or imputation, use the default `values: "analysis"` (`--values analysis`) to retain edited values; source mode would undo those edits.

Choose keys from the actual input, not the example. Source rows matching those keys must be unique; ambiguous or unmatched keys stop publication. `--date-keys` explicitly compares ISO civil dates, allowing a timestamp to match its date-only form. It preserves the matched source date-key text even in analysis-value mode; use `--analysis-key-values` only when the user requests that format change. It does not infer time zones; use full or prepared keys when time-of-day matters. A collision is an error, not permission to pick a row.

Choose `--numeric` only for fields established as numeric by the input and task. It validates finite numbers and removes incidental decimal-zero suffixes from ordinary integral representations; it does not round fractional data or convert undeclared identifier fields. Preserve full input precision during analysis and format chart labels separately.

The source and analysis files remain unchanged. The output is separate and create-only by default; replacing an existing output requires its observed `--expected-destination-sha256`. Input changes fail before publication. If a failure reports `writePublished: true`, inspect the output and reconcile its hash before considering another write.

Inspect the exported CSV and use it for the requested cleaned-data delivery, keeping derived features in the analysis data unless requested as output. When the destination is a service, use the task's authorized transfer interface and confirm remote delivery. Reopen requested charts or reports and state any unverified visual limitations.

Preserving an identifier means preserving which record it denotes, not treating every identifier as text. Inspect its source values: a field of unpadded whole-number identifiers promoted to decimal text by missing values can be included in `numeric` when cleaning types. Keep identifiers with meaningful leading zeros, prefixes or punctuation as strings. Include every chosen numeric field in the spec, even when its header is unnamed or contains spaces; do not infer the decision from the header alone.
