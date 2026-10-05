"""Draw the figure of the README from the committed evaluation reports.

    python -m countersign.eval.charts

One figure: what each configuration did with the documents of the confirmation split,
as a stacked bar per configuration. It is drawn twice, for light and dark pages.

Colours are identity, not judgement, except the last: blue, orange and aqua are the
first three slots of a palette checked for colour-blind separation in this order, and
red is reserved for decisions that do harm. Every segment that has room carries its
count, and the README gives the same numbers as a table.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle

from countersign.eval.metrics import DocumentScore, Report

ROWS: tuple[tuple[str, str], ...] = (
    ("small-unverified", "Small model, nothing checked"),
    ("large-unverified", "Large model, nothing checked"),
    ("small", "Small model + checks"),
    ("large", "Large model + checks"),
    ("cascade", "Cascade + checks"),
)
SEGMENTS: tuple[tuple[str, str], ...] = (
    ("approved", "Approved, correctly"),
    ("stopped", "Stopped, as required"),
    ("needless", "Sent to a person needlessly"),
    ("harmful", "Harmful: wrong approval, or invoice lost"),
)


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    ink: str
    secondary: str
    muted: str
    grid: str
    fills: tuple[str, str, str, str]


THEMES = (
    Theme(
        name="light",
        surface="#fcfcfb",
        ink="#0b0b0b",
        secondary="#52514e",
        muted="#898781",
        grid="#e1e0d9",
        fills=("#2a78d6", "#eb6834", "#1baf7a", "#d03b3b"),
    ),
    Theme(
        name="dark",
        surface="#1a1a19",
        ink="#ffffff",
        secondary="#c3c2b7",
        muted="#898781",
        grid="#2c2c2a",
        fills=("#3987e5", "#d95926", "#199e70", "#d03b3b"),
    ),
)


SPLIT_NAMES = {"dev": "development", "confirm": "confirmation"}


def classify(score: DocumentScore) -> str:
    if score.harm:
        return "harmful"
    if score.outcome == "approved":
        return "approved"
    return "stopped" if score.expected != "approved" else "needless"


def counts(report: Report) -> dict[str, int]:
    tally = dict.fromkeys((key for key, _ in SEGMENTS), 0)
    for score in report.documents:
        tally[classify(score)] += 1
    return tally


def _text_on(fill: str) -> str:
    """White or near-black, whichever reads on `fill`."""
    red, green, blue = (int(fill[index : index + 2], 16) / 255 for index in (1, 3, 5))
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#0b0b0b" if luminance > 0.5 else "#ffffff"


def draw(reports: dict[str, Report], split: str, theme: Theme, path: Path) -> None:
    rows = [(label, counts(reports[name])) for name, label in ROWS if name in reports]
    total = max(sum(tally.values()) for _, tally in rows)
    width_px, row_px, bar_px = 880, 46, 22
    top_px, bottom_px, left_px, right_px = 96, 44, 250, 96
    height_px = top_px + bottom_px + row_px * len(rows)
    figure = plt.figure(figsize=(width_px / 100, height_px / 100), dpi=100)
    figure.patch.set_facecolor(theme.surface)
    axes = figure.add_axes(
        (
            left_px / width_px,
            bottom_px / height_px,
            (width_px - left_px - right_px) / width_px,
            row_px * len(rows) / height_px,
        )
    )
    axes.set_facecolor(theme.surface)
    plot_px = width_px - left_px - right_px
    gap = 2 * total / plot_px  # two pixels of surface between segments, in documents

    for index, (label, tally) in enumerate(rows):
        y = len(rows) - 1 - index
        left = 0.0
        for (key, _), fill in zip(SEGMENTS, theme.fills, strict=True):
            count = tally[key]
            if count == 0:
                continue
            axes.add_patch(
                Rectangle(
                    (left + gap / 2, y - bar_px / row_px / 2),
                    max(count - gap, gap / 4),
                    bar_px / row_px,
                    color=fill,
                    linewidth=0,
                )
            )
            # A count is written inside its segment only where it has room to be read.
            if count * plot_px / total >= 6 + 7 * len(str(count)):
                axes.text(
                    left + count / 2,
                    y,
                    str(count),
                    ha="center",
                    va="center_baseline",
                    fontsize=9.5,
                    color=_text_on(fill),
                )
            elif key == "harmful":
                # One document in 270 is two pixels wide: too few to hide, so it is
                # written next to the bar.
                axes.text(
                    total * 1.012,
                    y,
                    f"{count} harmful",
                    ha="left",
                    va="center_baseline",
                    fontsize=9.5,
                    color=theme.secondary,
                    clip_on=False,
                )
            left += count
        axes.text(-total * 0.012, y, label, ha="right", va="center", fontsize=10.5, color=theme.ink)

    ticks = list(range(0, total + 1, 50))
    axes.set_xlim(0, total)
    axes.set_ylim(-0.6, len(rows) - 0.4)
    axes.set_xticks(ticks)
    axes.set_yticks([])
    axes.tick_params(axis="x", length=0, labelsize=9, labelcolor=theme.muted, pad=6)
    name = SPLIT_NAMES.get(split, split)
    axes.set_xlabel(f"documents of the {name} split ({total})", fontsize=9, color=theme.muted)
    axes.set_axisbelow(True)
    axes.grid(axis="x", color=theme.grid, linewidth=1)
    for spine in axes.spines.values():
        spine.set_visible(False)

    figure.text(
        0.02,
        1 - 28 / height_px,
        "What each configuration did with the same documents",
        fontsize=13,
        fontweight="bold",
        color=theme.ink,
    )
    renderer = figure.canvas.get_renderer()  # type: ignore[attr-defined]
    x = 0.02
    for (_, label), fill in zip(SEGMENTS, theme.fills, strict=True):
        figure.patches.append(
            Rectangle(
                (x, 1 - 62 / height_px),
                11 / width_px,
                11 / height_px,
                transform=figure.transFigure,
                color=fill,
                linewidth=0,
            )
        )
        entry = figure.text(
            x + 17 / width_px, 1 - 61 / height_px, label, fontsize=9.5, color=theme.secondary
        )
        # Each entry starts where the previous one really ends, whatever the font.
        x += (17 + entry.get_window_extent(renderer).width + 24) / width_px

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, facecolor=theme.surface, metadata={"Date": None})
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports", type=Path, default=Path("evals/reports"))
    parser.add_argument("--split", default="confirm")
    parser.add_argument("--out", type=Path, default=Path("docs/img"))
    arguments = parser.parse_args()

    reports = {}
    for name, _ in ROWS:
        path = arguments.reports / f"{arguments.split}-{name}.json"
        if path.exists():
            reports[name] = Report.model_validate_json(path.read_text(encoding="utf-8"))
    if not reports:
        print(f"no report for the {arguments.split} split under {arguments.reports}")
        return 2
    for theme in THEMES:
        target = arguments.out / f"outcomes-{theme.name}.svg"
        draw(reports, arguments.split, theme, target)
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
