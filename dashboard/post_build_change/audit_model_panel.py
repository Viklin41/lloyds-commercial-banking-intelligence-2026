"""Every number the model-scores panel puts on screen, traced back to a source.

Three classes of number appear on that panel and they do not have the same provenance,
which is the point of this audit:

  A. from the company parquet          -> the score, and the percentile band derived from it
  B. from the reasons parquet          -> the driver feature, value, weight and direction
  C. from store_meta.json              -> horizons, windows, precision, base rate, lift

C cannot be checked against either parquet, because held-out evaluation metrics are not in
them. It is checked against the meeting answers document instead, which is where it came from.
"""
import io, json, random, re, sys, urllib.request
import duckdb

SPINE = r"C:/Users/visha/Lloyds_Github/data/processed/dashboard_bulk_gazette_2026-07.parquet"
REASONS = r"C:/Users/visha/Lloyds_Github/lloyds-commercial-banking-intelligence-2026/dashboard/post_build_change/shortlist_reasons_2026-07.parquet"
META = r"C:/Users/visha/Lloyds_Github/lloyds-commercial-banking-intelligence-2026/dashboard/store_meta.json"
ANSWERS = r"C:/Users/visha/Lloyds_Github/lloyds-commercial-banking-intelligence-2026/dashboard/post_build_change/meeting-answers-2026-08-25.md"
API = "http://127.0.0.1:8000/api/company/"

con = duckdb.connect()
fails = []


def check(label, ok, detail=""):
    print(("   PASS  " if ok else "   FAIL  ") + label + (("  " + detail) if detail else ""))
    if not ok:
        fails.append(label)


# ---------------------------------------------------------------- A + B, per company
print("== A/B. Driver and score fields against the two parquets ==")
random.seed(20260826)
pool = [r[0] for r in con.execute(
    "SELECT DISTINCT CompanyNumber FROM read_parquet(?)", [REASONS]).fetchall()]
sample = random.sample(pool, 150)
# plus companies with no reasons at all, to check the absent path
nore = [r[0] for r in con.execute("""
    SELECT CompanyNumber FROM read_parquet(?) WHERE is_active
      AND CompanyNumber NOT IN (SELECT DISTINCT CompanyNumber FROM read_parquet(?))
    LIMIT 25""", [SPINE, REASONS]).fetchall()]

SCORE_COLS = ["lending", "insolvency", "growth", "voluntary_exit"]
n_drv = n_val = n_share = n_dir = n_lo = n_score = n_pct = 0
bad = []

for cn in sample + nore:
    rec = json.load(urllib.request.urlopen(API + cn))
    scores = rec.get("scores") or {}

    # every score shown must equal the parquet to 6dp
    prow = con.execute("SELECT %s FROM read_parquet(?) WHERE CompanyNumber = ?"
                       % ", ".join('"score_%s"' % c for c in SCORE_COLS),
                       [SPINE, cn]).fetchone()
    for c, want in zip(SCORE_COLS, prow):
        if c in scores:
            if abs(float(want) - scores[c]["score"]) > 5e-7:
                bad.append((cn, c, "score", want, scores[c]["score"]))
            n_score += 1
            # band position: count of active companies scoring strictly higher
            n = con.execute('SELECT count(*) FROM read_parquet(?) WHERE is_active '
                            'AND "score_%s" > ?' % c, [SPINE, float(want)]).fetchone()[0]
            tot = 1409284
            if abs(round(100.0 * n / tot, 2) - scores[c]["pct"]) > 0.02:
                bad.append((cn, c, "pct", round(100.0 * n / tot, 2), scores[c]["pct"]))
            n_pct += 1

    # every driver shown must exist as a row in the reasons parquet
    rows = con.execute("""SELECT target, rank_within_reason, feature, contribution, value
                          FROM read_parquet(?) WHERE CompanyNumber = ?
                          ORDER BY target, rank_within_reason""", [REASONS, cn]).fetchall()
    src = {}
    for t, rk, f, contrib, val in rows:
        src.setdefault(t, []).append((rk, f, contrib, val))

    for t in SCORE_COLS:
        shown = (scores.get(t) or {}).get("drivers")
        if t not in src:
            if shown:
                bad.append((cn, t, "drivers shown but none in file", None, None))
            continue
        if not shown:
            bad.append((cn, t, "drivers in file but none shown", None, None))
            continue
        if len(shown) != len(src[t]):
            bad.append((cn, t, "driver count", len(src[t]), len(shown)))
            continue
        total = sum(abs(c) for _, _, c, _ in src[t])
        for (rk, f, contrib, val), d in zip(src[t], shown):
            n_drv += 1
            if d["feature"] != f:
                bad.append((cn, t, "feature", f, d["feature"]))
            n_lo += 1
            if abs(round(contrib, 4) - d["logodds"]) > 1e-9:
                bad.append((cn, t, "logodds", contrib, d["logodds"]))
            n_share += 1
            want_share = round(100.0 * abs(contrib) / total, 1)
            if abs(want_share - d["share"]) > 0.05:
                bad.append((cn, t, "share", want_share, d["share"]))
            n_dir += 1
            want_dir = "up" if contrib > 0 else "down"
            if want_dir != d["direction"]:
                bad.append((cn, t, "direction", want_dir, d["direction"]))
            n_val += 1
            raw = "" if val is None else str(val).strip()
            missing = raw.lower() in {"nan", "none", "null", "", "na", "n/a"}
            try:
                fv = float(raw)
                if fv != fv or abs(fv) > 1200:
                    missing = True
            except ValueError:
                pass
            if missing and d["value"] is not None:
                bad.append((cn, t, "value should be suppressed", raw, d["value"]))
            if not missing and d["value"] is None:
                bad.append((cn, t, "value suppressed but usable", raw, None))

check("scores match the parquet (%d checked)" % n_score,
      not [b for b in bad if b[2] == "score"])
check("percentile bands recomputed from the parquet (%d checked)" % n_pct,
      not [b for b in bad if b[2] == "pct"])
check("driver feature names come from the reasons file (%d checked)" % n_drv,
      not [b for b in bad if b[2] == "feature"])
check("driver log-odds equal the file's contribution (%d checked)" % n_lo,
      not [b for b in bad if b[2] == "logodds"])
check("driver weights are |contribution| / row total (%d checked)" % n_share,
      not [b for b in bad if b[2] == "share"])
check("driver arrows follow the sign of contribution (%d checked)" % n_dir,
      not [b for b in bad if b[2] == "direction"])
check("driver values are the file's value, suppressed only when unusable (%d checked)" % n_val,
      not [b for b in bad if "value" in b[2]])
check("drivers appear exactly where the file has them, and nowhere else",
      not [b for b in bad if "drivers" in str(b[2]) or b[2] == "driver count"])
if bad:
    print("\n   first 10 discrepancies:")
    for b in bad[:10]:
        print("     ", b)

# ---------------------------------------------------------------- C, against the source doc
print("\n== C. store_meta figures against the meeting answers document ==")
meta = json.load(io.open(META, encoding="utf-8"))
doc = io.open(ANSWERS, encoding="utf-8").read()

# The Q5 table: | `target` | origin | base rate | P@100 | Lift@100 | P@500 | Lift@500 |
q5 = {}
for m in re.finditer(r"\|\s*`(\w+)`\s*\|\s*([\d-]+)\s*\|\s*([\d.]+)%\s*\|\s*([\d.]+)\s*\|"
                     r"\s*(\d+)x\s*\|", doc):
    t, origin, base, p100, lift = m.groups()
    q5.setdefault(t, []).append((float(base), float(p100), int(lift)))

for m in meta["score_models"]:
    t = m["key"].replace("score_", "")
    if t not in q5:
        check("Q5 rows found for %s" % t, False)
        continue
    bases = [x[0] for x in q5[t]]
    p100s = [x[1] for x in q5[t]]
    lifts = [x[2] for x in q5[t]]
    ok = (m["base_rate_pct_low"] == min(bases) and m["base_rate_pct_high"] == max(bases)
          and m["p100_low"] == min(p100s) and m["p100_high"] == max(p100s)
          and m["lift_low"] == min(lifts) and m["lift_high"] == max(lifts))
    check("%-15s base %s-%s  P@100 %s-%s  lift %s-%s" % (
              t, m["base_rate_pct_low"], m["base_rate_pct_high"],
              m["p100_low"], m["p100_high"], m["lift_low"], m["lift_high"]),
          ok,
          "" if ok else "document says base %s p100 %s lift %s" % (bases, p100s, lifts))
    check("   %s lift_about lies inside the measured range" % t,
          min(lifts) <= m["lift_about"] <= max(lifts))

# ---------------------------------------------------------------- reasons block
print("\n== The reasons coverage block against the reasons parquet ==")
r = meta["reasons"]
q = lambda s: con.execute(s, [REASONS]).fetchone()[0]
check("distinct_companies = %d" % r["distinct_companies"],
      q("SELECT count(DISTINCT CompanyNumber) FROM read_parquet(?)") == r["distinct_companies"])
check("companies_per_target = %d for all four" % r["companies_per_target"],
      q("SELECT min(n) FROM (SELECT count(DISTINCT CompanyNumber) AS n FROM read_parquet(?) GROUP BY target)")
      == r["companies_per_target"])
check("reasons_per_company = %d for every pair" % r["reasons_per_company"],
      q("SELECT min(n) FROM (SELECT count(*) AS n FROM read_parquet(?) GROUP BY CompanyNumber, target)")
      == r["reasons_per_company"]
      and q("SELECT max(n) FROM (SELECT count(*) AS n FROM read_parquet(?) GROUP BY CompanyNumber, target)")
      == r["reasons_per_company"])
check("targets listed match the file",
      sorted(x[0] for x in con.execute("SELECT DISTINCT target FROM read_parquet(?)", [REASONS]).fetchall())
      == sorted(r["targets"]))
cov = 100.0 * r["companies_per_target"] / meta["scored_companies"]
check("coverage note says 0.35%%, computed %.2f%%" % cov, abs(cov - 0.35) < 0.005)

# ---------------------------------------------------------------- feature labels
print("\n== Every feature in the file has a label ==")
feats = [x[0] for x in con.execute("SELECT DISTINCT feature FROM read_parquet(?)", [REASONS]).fetchall()]
sys.path.insert(0, r"C:/Users/visha/Lloyds_Github/lloyds-commercial-banking-intelligence-2026/dashboard")
src = io.open(r"C:/Users/visha/Lloyds_Github/lloyds-commercial-banking-intelligence-2026/dashboard/serve.py",
              encoding="utf-8").read()
labelled = set(re.findall(r'^\s{4}"([^"]+)":\s*"', src[src.index("FEATURE_LABELS = {"):src.index("# Features whose stored")], re.M))
missing = sorted(set(feats) - labelled)
check("all %d features in the file are labelled" % len(feats), not missing,
      "" if not missing else "missing: " + ", ".join(missing))

print("\n" + ("ALL CHECKS PASSED" if not fails else "FAILURES: %d -> %s" % (len(fails), fails)))
