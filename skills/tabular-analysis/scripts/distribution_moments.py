"""Descriptive moments with explicit population and corrected sample conventions."""

import math


def moments(values):
    count = len(values)
    result = {
        "observations": count,
        "mean": None,
        "minimum": None,
        "maximum": None,
        "standardDeviationSample": None,
        "kurtosisPearsonPopulation": None,
        "kurtosisExcessPopulation": None,
        "kurtosisExcessUnbiased": None,
    }
    if not count:
        return {**result, "unavailable": "no_observations"}
    result.update(minimum=min(values), maximum=max(values))
    scale = max(abs(value) for value in values)
    normalized = [value / scale for value in values] if scale else values
    average = math.fsum(normalized) / count
    centered = [value - average for value in normalized]
    second = math.fsum(value * value for value in centered) / count
    result["mean"] = average * scale
    if count > 1:
        deviation = math.sqrt(second * count / (count - 1)) * scale
        result["standardDeviationSample"] = (
            deviation if math.isfinite(deviation) else None
        )
    if not second:
        return {**result, "unavailable": "constant_values"}
    fourth = math.fsum(value**4 for value in centered) / count
    pearson = fourth / (second * second)
    excess = pearson - 3
    result.update(kurtosisPearsonPopulation=pearson, kurtosisExcessPopulation=excess)
    if count >= 4:
        result["kurtosisExcessUnbiased"] = (
            (count - 1) * ((count + 1) * excess + 6) / ((count - 2) * (count - 3))
        )
    return result
