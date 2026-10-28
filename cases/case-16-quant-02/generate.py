"""Generate the public synthetic inputs; no market feed, credentials or model calls."""

import argparse
import json
import math
from pathlib import Path


def inputs():
    bars = []
    for index in range(180):
        close = round(100 + 8 * math.sin(index / 3) + index / 8, 2)
        bars.append(
            {
                "bar": index,
                "open": round(close + (3 if index % 9 == 0 else -1), 2),
                "close": close,
            }
        )
    return {
        "bars": bars,
        "initial_cash": 10000,
        "fee": 0.001,
        "slippage": 0.001,
        "train": [0, 100],
        "validation": [100, 140],
        "test": [140, 180],
        "candidates": [[3, 5], [3, 8], [5, 10]],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).parent / "inputs/prices.json"
    )
    output = parser.parse_args().output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(inputs(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(output)


if __name__ == "__main__":
    main()
