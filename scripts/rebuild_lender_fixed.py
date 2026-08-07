"""Rebuild the lender panel and matrix under a corrected as-of gate.

Stage 1 replays the charge history into the config's lender panel, stage 2 rebuilds
its training matrix. Each gate gets its own directories and the leaky originals are
left where they are: the before/after is the point.

    lender_fixed   gate on delivered_on
    lender_asof21  gate on delivered_on + charges.REGISTRATION_LAG_DAYS

Same resumable shape as `run_config_staged.py`, for the same reason.

    python scripts/rebuild_lender_fixed.py lender_asof21
    python scripts/run_config_staged.py    lender_asof21
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features import charges
from src.models import targets, train

CFG = {"lender_fixed": train.LENDER_FIXED,
       "lender_asof21": train.LENDER_ASOF21}[sys.argv[1]]
STAGE = Path("data/processed/run_stage") / f"{CFG.tag}_build"
STAGE.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(f"[{pd.Timestamp.now():%H:%M:%S}] {msg}", flush=True)


# --- stage 1: the lender panel --------------------------------------------- #
if not (STAGE / "panel.done").exists():
    log(f"building {CFG.lender_dir} (registration lag {charges.REGISTRATION_LAG_DAYS}d)")
    n = charges.build_lender_panel(out_dir=CFG.lender_dir, threads=6)
    (STAGE / "panel.done").write_text(str(n))
    log(f"{n:,} company-month rows")

# --- stage 2: the training matrix ------------------------------------------ #
for name in CFG.target_names:
    if (STAGE / f"matrix_{name}.done").exists():
        continue
    log(f"building matrix: {name}")
    s = targets.build_matrix(name, lender_dir=CFG.lender_dir,
                             out_dir=CFG.matrix_dir, threads=6)
    (STAGE / f"matrix_{name}.done").write_text(
        f"{int(s['rows'].sum())} rows, {int(s['positives'].sum())} positives")
    log(f"{name}: {s['rows'].sum():,} rows, {int(s['positives'].sum()):,} positives")

log(f"rebuild complete; run scripts/run_config_staged.py {CFG.tag} next")
