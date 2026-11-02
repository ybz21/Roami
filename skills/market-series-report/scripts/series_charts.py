"""Chart axes and legends; slide headings own titles to avoid duplicate text layers."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import EngFormatter

BLUE, TEAL, NAVY, ORANGE = "#2168A6", "#168D86", "#15334F", "#C96E28"


def charts(folder, facts, series, font):
    plt.rcParams.update(
        {
            "font.family": font,
            "font.size": 13,
            "axes.labelsize": 14,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#CAD4DD",
            "axes.grid": True,
            "grid.color": "#E5EBF0",
            "axes.axisbelow": True,
        }
    )
    paths = []

    def save(fig, name):
        fig.tight_layout(pad=1.6)
        path = folder / (name + ".png")
        fig.savefig(path, dpi=135, facecolor="white")
        plt.close(fig)
        paths.append(path)

    def dated(axis):
        locator = mdates.AutoDateLocator(
            minticks=4, maxticks=7, tz=series["price"].index.tz
        )
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(locator, tz=series["price"].index.tz)
        )
        axis.set_xlabel("Observation date (" + str(series["price"].index.tz) + ")")

    price, volume, returns = (series[name] for name in ("price", "volume", "returns"))
    fig, ax = plt.subplots(figsize=(10.5, 6))
    ax.plot(price.index, price, color=BLUE, linewidth=1.8)
    ax.set_ylabel(facts["columns"]["price"] + " (" + facts["units"]["price"] + ")")
    dated(ax)
    save(fig, "price")
    fig, ax = plt.subplots(figsize=(10.5, 6))
    ax.plot(
        price.index,
        price,
        color=BLUE,
        linewidth=1,
        alpha=0.6,
        label=facts["columns"]["price"],
    )
    for key, color in [("short", ORANGE), ("long", NAVY)]:
        ax.plot(
            price.index,
            series[key],
            color=color,
            linewidth=1.8,
            label=str(facts["movingAverages"][key + "Window"]) + " observations",
        )
    ax.legend(loc="upper left", frameon=False)
    ax.set_ylabel("Price (" + facts["units"]["price"] + ")")
    dated(ax)
    save(fig, "moving-averages")
    values = np.array(
        [
            [np.nan if v is None else v for v in row]
            for row in facts["correlation"]["values"]
        ]
    )
    labels = facts["correlation"]["labels"]
    fig, ax = plt.subplots(figsize=(10.5, 6))
    image = ax.imshow(np.ma.masked_invalid(values), vmin=-1, vmax=1, cmap="RdBu")
    ax.grid(False)
    ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for row in range(len(labels)):
        for col in range(len(labels)):
            value = values[row, col]
            ax.text(
                col,
                row,
                "n/a" if np.isnan(value) else f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=11,
                color="white" if abs(value) > 0.65 else NAVY,
            )
    fig.colorbar(
        image, ax=ax, fraction=0.04, pad=0.03, label="Same-row Pearson correlation"
    )
    save(fig, "correlation")
    fig, ax = plt.subplots(figsize=(10.5, 6))
    ax.hist(returns * 100, bins="auto", color=BLUE, edgecolor="white", linewidth=0.5)
    ax.axvline(0, color=NAVY, linewidth=1)
    ax.set_xlabel("Successive observed price change (%)")
    ax.set_ylabel("Observations")
    save(fig, "returns")
    fig, ax = plt.subplots(figsize=(10.5, 6))
    ax.hist(volume, bins="auto", color=TEAL, edgecolor="white", linewidth=0.5)
    ax.axvline(
        facts["volume"]["median"],
        color=ORANGE,
        linestyle="--",
        linewidth=2,
        label="Median " + f"{facts['volume']['median']:,.0f}",
    )
    ax.legend(frameon=False)
    ax.xaxis.set_major_formatter(EngFormatter(places=0, sep=""))
    ax.set_xlabel(facts["columns"]["volume"] + " (" + facts["units"]["volume"] + ")")
    ax.set_ylabel("Observations")
    save(fig, "volume")
    fig, ax = plt.subplots(figsize=(10.5, 6))
    ax.fill_between(price.index, series["drawdown"] * 100, 0, color=BLUE, alpha=0.18)
    ax.plot(price.index, series["drawdown"] * 100, color=BLUE, linewidth=1.5)
    ax.set_ylabel("Decline from historical price peak (%)")
    dated(ax)
    save(fig, "drawdown")
    return paths
