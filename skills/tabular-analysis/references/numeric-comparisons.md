# Comparing reported quantities

Prepare two CSV snapshots for the actual periods or groups requested by the task. Choose the grouping and units from the supplied data; this command does not infer dates, clean rows, or choose the comparison. Inspect the snapshots to obtain their hashes.

```sh
python <packagePath>/scripts/numeric_comparison.py --workspace <directory> --baseline before.csv --current after.csv --columns "quantity" --statistic median --expected-baseline-sha256 <observed-hash> --expected-current-sha256 <observed-hash>
```

Choose `mean`, `median`, `minimum`, `maximum`, `first`, or `last` explicitly. `first` and `last` follow input row order. The receipt names the snapshots, hashes, observation counts, missing cells and statistic. It reads without writing either input and rejects changed sources, invalid numeric cells or empty samples. Empty cells are omitted separately; their counts remain visible.

Use `difference` for current minus baseline, `fractionalChange` for current divided by baseline minus one, and `percentageDisplay` for that fraction multiplied by 100 and displayed to one decimal place. Numeric values are decimal strings; calculations use 50 significant digits and round-half-even. Keep full values for further calculations and use display formatting only in the report.

Copy the computed percentage and its actual statistic into slide text and the presenter script. A ratio or percentage is not a reason to substitute an inaccurate qualitative phrase. Check thresholds against unrounded values: a display of zero percent does not prove no change, and rounding an extreme does not establish that it crossed a threshold.

At a zero baseline the difference remains available, but percentage fields are null. Do not invent a percentage. With a negative baseline, the signed ratio may point opposite to the numeric direction; inspect the declared formula and `direction` before describing a change. Comparisons establish descriptive differences only; forecasts and external benchmarks need separate evidence.
