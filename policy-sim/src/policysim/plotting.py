"""Event-study plots.

Labels are English on purpose: the container has no Korean-capable font, and
matplotlib renders missing glyphs as empty boxes. Install a font such as
NanumGothic and set rcParams['font.family'] locally if Korean labels are wanted.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .event_study import EventStudyResult  # noqa: E402

_STYLE = {
    "treated": {"color": "#c0392b", "label": "Treated (regulated)"},
    "adjacent": {"color": "#2980b9", "label": "Adjacent (spillover)"},
}


def plot_event_study(
    result: EventStudyResult,
    path: Path,
    title: str = "Event study",
    truth: float | None = None,
) -> Path:
    figure, axis = plt.subplots(figsize=(10, 5.5))

    for series, style in _STYLE.items():
        subset = result.coefficients.loc[result.coefficients["series"] == series]
        if subset.empty:
            continue
        axis.plot(subset["event_time"], subset["estimate"], marker="o", ms=3.5, **style)
        axis.fill_between(
            subset["event_time"],
            subset["ci_low"],
            subset["ci_high"],
            color=style["color"],
            alpha=0.15,
            linewidth=0,
        )

    axis.axvline(-0.5, color="black", linestyle="--", linewidth=1)
    axis.axhline(0, color="black", linewidth=0.8)
    if truth is not None:
        axis.axhline(truth, color="#27ae60", linestyle=":", linewidth=1.6, label="True effect")

    axis.set_xlabel("Months relative to policy (baseline = pre-period mean)")
    axis.set_ylabel("Log price index vs. control")
    axis.set_title(title)
    axis.legend(loc="lower left", frameon=False)
    axis.grid(alpha=0.25, linewidth=0.5)

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path
