"""Render the run registry as a standalone landscape PDF for the report appendix.

The registry is 128 metric rows across eleven runs, which is more than a LaTeX
table in a portrait dissertation can hold without breaking its own margins. So it
is typeset here instead, straight from `reports/runs/index.csv` and the manifests,
and dropped into Overleaf with `\\includepdf` under Appendix B, which supplies the
chapter heading and the page numbers. This file therefore carries the three
numbered tables and nothing else: no title, no running footer, no prose. The
numbers cannot drift from what is on disk because nothing here is retyped.

    python scripts/make_run_registry_pdf.py   ->  reports/run_registry.pdf
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "reports" / "runs"
OUT = REPO_ROOT / "reports" / "run_registry.pdf"

# Run order: the two controls first, then the gate story in the order it happened,
# then the calibrated runs the verdict is actually read off.
ORDER = ["baseline", "refactor", "refactor_det", "refactor_growthfix",
         "lender", "lender_fixed", "lender_asof21", "lender_asof21_det",
         "lender_calib_lo", "lender_calib", "lender_calib_hi"]

# What each run is, one line each. Same wording as reports/runs/README.md.
WHAT = {
    "baseline": "First recorded run. 41 features, boosted and linear only, no MLP and no intervals. The fixed reference every later run is a diff against.",
    "refactor": "The control after the pipeline rewrite: same matrix, same 41 features (same hash), full registry including the MLP.",
    "refactor_det": "refactor under LightGBM determinism, with bootstrap intervals and per-origin metrics. The control every later run is read against.",
    "refactor_growthfix": "The control with growth cut to the 27 features that exist at its training origins. Other three targets untouched.",
    "lender": "The A/B: +13 lender-identity columns from the Charges harvest. Its lending numbers are contaminated by the as-of gate and are kept as the exhibit of it.",
    "lender_fixed": "The A/B with the gate moved to delivered_on. Halves the distortion and is still contaminated (lending P@500 = 0.742).",
    "lender_asof21": "The A/B with delivered_on plus a 21-day registration lag. Superseded: the 21 days were mostly a satisfaction-clock error.",
    "lender_asof21_det": "lender_asof21 under determinism. Re-baselines the lender A/B; every delta reproduced exactly.",
    "lender_calib_lo": "The calibrated gate at its loosest tested setting. Not a verdict run; it exists to show the gradient.",
    "lender_calib": "The calibrated gate at the point estimate, 4 days on creation and 1 on satisfaction.",
    "lender_calib_hi": "The calibrated gate at the leak-averse end, 7 days and 3 days. The run the lender verdict should be read off.",
}

# The true as-of gate per run, as the lender panel was actually built. Source of truth
# is the build table in notebooks/14b_lender_charges.ipynb together with
# scripts/run_config_staged.py, not the manifests, which record the module default of the
# day on six of the eleven runs. The clock matters as much as the lag, because the
# calibrated panels moved the as-of date from the nominal snapshot to the source extract
# date.
TRUE_GATE = {
    "baseline": "n/a, no lender features",
    "refactor": "n/a, no lender features",
    "refactor_det": "n/a, no lender features",
    "refactor_growthfix": "n/a, no lender features",
    "lender": "created_on, no lag, snapshot clock",
    "lender_fixed": "delivered_on, no lag, snapshot clock",
    "lender_asof21": "delivered_on, 21d created / 0d satisfied, snapshot clock",
    "lender_asof21_det": "delivered_on, 21d created / 0d satisfied, snapshot clock",
    "lender_calib_lo": "delivered_on, 2d created / 1d satisfied, extract clock",
    "lender_calib": "delivered_on, 4d created / 1d satisfied, extract clock",
    "lender_calib_hi": "delivered_on, 7d created / 3d satisfied, extract clock",
}

# Six runs are comparable to one another and carry intervals on all twelve cells; the
# other five are retained as diagnostic. Same split the body of the report tabulates.
ROLE = {
    "baseline": "diagnostic: historical reference, predates the MLP and the bootstrap",
    "refactor": "diagnostic: superseded by refactor_det, which reproduces it",
    "refactor_det": "comparable: the control every later run is read against",
    "refactor_growthfix": "comparable: the shipped model",
    "lender": "diagnostic: leak exhibit, P@100 = 1.000",
    "lender_fixed": "diagnostic: leak exhibit, P@500 = 0.742",
    "lender_asof21": "diagnostic: superseded by lender_asof21_det, which reproduces it",
    "lender_asof21_det": "comparable: the A/B at the 21-day gate",
    "lender_calib_lo": "comparable: the loosest gate tested",
    "lender_calib": "comparable: the calibrated gate at the point estimate",
    "lender_calib_hi": "comparable: the tightest gate, the lender verdict is read off this",
}

NICE_TARGET = {"lending": "Lending Readiness", "insolvency": "Credit Risk",
               "voluntary_exit": "Voluntary Exit", "growth": "Growth Signal"}
NICE_MODEL = {"lightgbm": "LightGBM", "logistic": "Logistic", "mlp": "MLP"}

GREY = colors.HexColor("#f2f2f2")
RULE = colors.HexColor("#444444")
LIGHT = colors.HexColor("#bbbbbb")


def styles():
    ss = getSampleStyleSheet()
    return {
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                             fontSize=10.5, spaceBefore=10, spaceAfter=5),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=6.4, leading=7.6),
        "mono": ParagraphStyle("mono", fontName="Courier", fontSize=6.4, leading=7.6),
    }


def table_style(header_rows=1, extra=()):
    return TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 6.4),
        ("FONT", (0, 0), (-1, header_rows - 1), "Helvetica-Bold", 6.6),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, RULE),
        ("LINEBELOW", (0, header_rows - 1), (-1, header_rows - 1), 0.6, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        *extra,
    ])


def fmt(v, nd=4):
    return "" if pd.isna(v) else f"{v:.{nd}f}"


def interval(lo, hi, nd=4):
    if pd.isna(lo) or pd.isna(hi):
        return "not recorded"
    return f"[{lo:.{nd}f}, {hi:.{nd}f}]"


def load():
    idx = pd.read_csv(RUNS_DIR / "index.csv")
    manifests, metrics = {}, {}
    for tag in ORDER:
        manifests[tag] = json.loads((RUNS_DIR / tag / "manifest.json").read_text())
        metrics[tag] = json.loads((RUNS_DIR / tag / "metrics.json").read_text())
    return idx, manifests, metrics


def feature_count(idx, tag):
    """Feature count as recorded per target, since `growth` differs on the fix run."""
    per_target = idx[idx["tag"] == tag].groupby("target")["n_features"].first()
    counts = sorted(set(per_target))
    if len(counts) == 1:
        return str(counts[0])
    odd = per_target[per_target != per_target.mode().iloc[0]]
    return f"{per_target.mode().iloc[0]} ({odd.iloc[0]} for {odd.index[0]})"


def config_table(idx, manifests, st):
    head = ["Tag", "Recorded", "Git SHA", "Matrix directory", "Features",
            "Feature hash", "Model families", "As-of gate on the lender panel (true)"]
    rows = [head]
    for tag in ORDER:
        m = manifests[tag]
        rows.append([
            Paragraph(f"<b>{tag}</b>", st["mono"]),
            m.get("created_at", "")[:10],
            m.get("git_sha") or "pre-manifest",
            Paragraph(Path(m["matrix_dir"]).name, st["mono"]),
            Paragraph(feature_count(idx, tag), st["cell"]),
            Paragraph(m.get("feature_hash", ""), st["mono"]),
            ", ".join(NICE_MODEL.get(x, x) for x in m.get("models", [])),
            Paragraph(TRUE_GATE[tag], st["cell"]),
        ])
    widths = [30, 16, 17, 44, 17, 20, 38, 45]
    t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(table_style(extra=[
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY]),
    ]))
    return t


def what_table(st):
    rows = [["Tag", "Role", "What the run is"]]
    for tag in ORDER:
        rows.append([Paragraph(f"<b>{tag}</b>", st["mono"]),
                     Paragraph(ROLE[tag], st["cell"]),
                     Paragraph(WHAT[tag], st["cell"])])
    t = Table(rows, colWidths=[30 * mm, 62 * mm, 140 * mm], repeatRows=1)
    t.setStyle(table_style(extra=[
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY]),
    ]))
    return t


def metrics_table(idx, metrics, st):
    head = ["Run", "Target", "Model", "Train rows", "Train pos.", "Eval rows",
            "Eval pos.", "Base rate", "ROC-AUC", "ROC-AUC 95% CI", "PR-AUC",
            "P@100", "P@500", "P@500 95% CI", "P@1000"]
    rows = [head]
    spans, shade = [], []
    for tag in ORDER:
        sub = idx[idx["tag"] == tag]
        if sub.empty:
            continue
        sub = sub.assign(_t=sub["target"].map({t: i for i, t in enumerate(NICE_TARGET)}),
                         _m=sub["model"].map({m: i for i, m in enumerate(NICE_MODEL)}))
        sub = sub.sort_values(["_t", "_m"])
        first = len(rows)
        for j, (_, r) in enumerate(sub.iterrows()):
            ev = metrics[tag]["targets"][r["target"]]["metrics"][r["model"]]
            rows.append([
                Paragraph(tag, st["mono"]) if j == 0 else "",
                NICE_TARGET.get(r["target"], r["target"]),
                NICE_MODEL.get(r["model"], r["model"]),
                f"{int(r['train_rows']):,}",
                f"{int(r['train_positives']):,}",
                f"{int(ev['n']):,}",
                f"{int(ev['positives']):,}",
                f"{r['base_rate'] * 100:.3f}%",
                fmt(r["roc_auc"]),
                interval(r["roc_auc_lo"], r["roc_auc_hi"]),
                fmt(r["pr_auc"]),
                fmt(r["precision_at_100"], 3),
                fmt(r["precision_at_500"], 3),
                interval(r["precision_at_500_lo"], r["precision_at_500_hi"], 3),
                fmt(r["precision_at_1000"], 3),
            ])
        last = len(rows) - 1
        spans.append(("SPAN", (0, first), (0, last)))
        spans.append(("LINEABOVE", (0, first), (-1, first), 0.4, LIGHT))
        if ORDER.index(tag) % 2:
            shade.append(("BACKGROUND", (0, first), (-1, last), GREY))
    widths = [24, 23, 14, 18, 15, 18, 14, 14, 15, 26, 14, 12, 12, 22, 12]
    t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(table_style(extra=[
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 1), (0, -1), "MIDDLE"),
        *shade, *spans,
    ]))
    return t


def main():
    idx, manifests, metrics = load()
    st = styles()
    doc = SimpleDocTemplate(
        str(OUT), pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title="Run registry", author="Team 5",
    )

    story = [
        Paragraph("B.1 &nbsp; Configuration of each recorded run", st["h2"]),
        config_table(idx, manifests, st),
        Spacer(1, 8),
        Paragraph("B.2 &nbsp; Run comparability", st["h2"]),
        what_table(st),
        PageBreak(),
        Paragraph("B.3 &nbsp; Full metric table: one row per run × target × model", st["h2"]),
        Spacer(1, 2),
        metrics_table(idx, metrics, st),
    ]

    doc.build(story)
    print(f"wrote {OUT.relative_to(REPO_ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
