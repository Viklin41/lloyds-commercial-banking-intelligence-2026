"""Report artefacts: figures and tables written to disk so LaTeX can cite them.

Every figure in this repo used to live only inside a notebook's stored output,
which means a report built with ``\\includegraphics`` had nothing to point at, and
every number in the write-up had to be retyped by hand from a notebook cell. Both
of those are how a report ends up disagreeing with its own artefacts.

So: one place figures go, one place tables go, and both callable from any notebook.
PNG at 200dpi is for reading in the notebook, PDF is the vector copy LaTeX wants.
Tables get a CSV (so the numbers stay machine-readable) and a matching .tex.
"""

from __future__ import annotations

from pathlib import Path

FIG_DIR = Path("reports/figures")
TAB_DIR = Path("reports/tables")


def save_fig(fig, name: str) -> Path:
    """Write a figure to ``reports/figures/<name>.{png,pdf}``, return the PDF path."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / f"{name}.png", dpi=200, bbox_inches="tight")
    pdf = FIG_DIR / f"{name}.pdf"
    fig.savefig(pdf, bbox_inches="tight")
    return pdf


def save_table(df, name: str, caption: str = "") -> Path:
    """Write ``reports/tables/<name>.csv`` and a matching ``.tex``, return the .tex path."""
    TAB_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(TAB_DIR / f"{name}.csv", index=False)
    tex = TAB_DIR / f"{name}.tex"
    tex.write_text(df.to_latex(index=False, caption=caption or None, label=f"tab:{name}"))
    return tex
