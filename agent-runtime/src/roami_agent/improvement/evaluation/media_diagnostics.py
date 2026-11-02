"""Public numeric components of a media verdict, without reference material."""

import math

AUDIO_METRICS = {
    "in_window_reward": (),
    "out_window_reward": (),
    "in_window": (
        "pesq_wb",
        "stoi",
        "lsd_full",
        "lsd_4_8kHz",
        "f0_corr",
        "dnsmos_sig",
        "dnsmos_bak",
        "dnsmos_ovl",
    ),
    "out_window": ("out_si_sdr_db", "out_n_samples"),
}


def audio_diagnostic(value):
    if not isinstance(value, dict):
        return None
    result = {}
    for group, fields in AUDIO_METRICS.items():
        if not fields:
            if group in value:
                observed = value[group]
                result[group] = (
                    observed
                    if type(observed) in (int, float)
                    and -1e12 <= observed <= 1e12
                    and math.isfinite(observed)
                    else None
                )
            continue
        entries = value.get(group)
        if isinstance(entries, dict):
            selected = {
                key: observed
                if type(observed) in (int, float)
                and -1e12 <= observed <= 1e12
                and math.isfinite(observed)
                else None
                for key in fields
                if key in entries
                for observed in [entries[key]]
            }
            if selected:
                result[group] = selected
    return result or None
