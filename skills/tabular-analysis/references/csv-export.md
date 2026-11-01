# Cleaned CSV publication

Use the bundled export command for a cleaned CSV copy. It preserves source columns and order, excludes analysis-only fields, and can recover omitted source columns through explicit keys. Include unnamed identifier columns; use `--columns` only for a different schema requested by the user. Decide row cleaning and analysis from the task.

Column identity and stored representation are separate choices. For requested numeric type cleanup, normalize unpadded whole-number identifiers promoted to decimal text, including unnamed columns, with `numeric`; their record identities stay the same. Keep meaningful leading zeros, prefixes, punctuation or explicitly requested text formats with `preserveNumericText`. Use the observed values and task to choose; an identifier-like header alone is not a reason to retain decimal-zero text.

Read this Skill's `packagePath` from the tool result. The scripts use Python's standard library and need no package installation.

Use the original downloaded input as `source`, before any normalization or rounding; a cleaned intermediate table is `analysis`, not a replacement source. Inspect both snapshots, then write the export choices as a JSON file. Arrays keep each full column name intact even when names contain spaces, quotes, Unicode or shell characters.

```sh
python <packagePath>/scripts/csv_export.py inspect --workspace <directory> --path raw.csv
python <packagePath>/scripts/csv_export.py inspect --workspace <directory> --path analysis.csv
```

Write `export.json` using the actual columns and the two observed hashes:

Inspection reports `integralDecimalFields`: exact field names and counts of decimal-form whole numbers, numeric values, and leading-zero representations. Review every listed field, including empty or unnamed headers, when cleaning types. These are observations, not automatic type decisions; mixed values and padded identifiers require deliberate treatment.

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
  "numeric": ["record index", "units", "total amount"],
  "preserveNumericText": ["padded code"]
}
```

```sh
python <packagePath>/scripts/csv_export.py export --workspace <directory> --spec export.json
```

`numeric` is required in a spec: list the fields whose numeric representations should be normalized, or explicitly use `[]` if none. Omitting it is rejected, so a forgotten selection cannot silently skip the decision. Every exported field retaining decimal-form whole numbers must be declared in either `numeric` or `preserveNumericText` (`--preserve-numeric-text`). Undeclared fields stop the write with their exact names and observed counts. Select preservation only when the task calls for unchanged text, such as padded or mixed identifiers; do not acknowledge a missed conversion merely to clear an error. A field cannot be in both lists. The spec accepts the same options as individual flags: `columns`, `analysisKeyValues`, and `expectedDestinationSha256` are optional. Do not mix `--spec` with individual export options. For direct flags, use structured `bash.argv` items for full field names. If field selection fails, use the returned rejected names and available columns to repair quoting or the JSON; do not drop intended conversions just to clear an error.

For cleaning that only filters/reorders rows or normalizes selected numeric representations, `values: "source"` (`--values source`) retains the matching original field values and representations, including timestamp/time-zone text. The selected `numeric` conversions still run in source mode; type cleanup alone does not require analysis mode. For actual cell-value corrections or imputation, use the default `values: "analysis"` (`--values analysis`) to retain edited values; source mode would undo those edits.

CSV stores text rather than in-memory column types. Parsing a key to datetime for filtering or sorting is not by itself a request to shorten its exported timestamp or remove its time zone. For type conversion alone, keep the matched source key text; choose analysis key text only for an explicitly requested serialization-format change.

Choose keys from the actual input, not the example. Source rows matching those keys must be unique; ambiguous or unmatched keys stop publication. `--date-keys` explicitly compares ISO civil dates, allowing a timestamp to match its date-only form. It preserves the matched source date-key text even in analysis-value mode; use `--analysis-key-values` only when the user requests that format change. It does not infer time zones; use full or prepared keys when time-of-day matters. A collision is an error, not permission to pick a row.

Choose `--numeric` only for fields established as numeric by the input and task. It validates finite numbers and removes incidental decimal-zero suffixes from ordinary integral representations; it does not round fractional data or convert undeclared identifier fields. Preserve full input precision during analysis and format chart labels separately.

The source and analysis files remain unchanged. The output is separate and create-only by default; replacing an existing output requires its observed `--expected-destination-sha256`. Input changes fail before publication. The export receipt names `numericFields` and `retainedIntegralDecimalFields`; check that retained representations are intentional before delivery. If a field has no type choice, correct the selection before publication. Replacing a prior output still requires its observed destination hash. If a failure reports `writePublished: true`, inspect the output and reconcile its hash before considering another write.

Inspect the exported CSV and use it for the requested cleaned-data delivery, keeping derived features in the analysis data unless requested as output. When the destination is a service, use the task's authorized transfer interface and confirm remote delivery. Reopen requested charts or reports and state any unverified visual limitations.
