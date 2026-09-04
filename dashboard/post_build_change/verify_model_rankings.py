"""Every number the Model Rankings view puts on screen, recomputed from the parquet.

Ground truth is written here from the column semantics rather than lifted from serve.py, so
that agreement between the two means something. Run with the server up:

    python dashboard/post_build_change/verify_model_rankings.py

RANKING LOGIC UNDER TEST
------------------------
  Lending    -> score_lending
  Insolvency -> score_insolvency
  Growth     -> score_growth

  population : is_active. No active company has a null score, so active and scored are the
               same 1,409,284 rows and the denominator on screen is honest.
  order      : the chosen score DESCENDING.
  tie-break  : CompanyNumber ASCENDING, matching TIE_BREAK everywhere else in the server.
  rank       : row_number() over exactly that ordering, cut at 100. The rank is produced by
               the same window that orders the rows, so the number beside a company and its
               position in the list cannot disagree.
  excluded   : voluntary exit, because 138 companies share its rank-100 score. Positions 100
               to 237 would be one arbitrary tie-break apart, and a numbered list would be
               asserting an order the data does not contain. This script re-measures that.
"""
import json
import os
import urllib.request
from pathlib import Path

import duckdb

_REPO = Path(__file__).resolve().parents[2]
_DATA = Path(os.environ.get("LLOYDS_DATA") or _REPO / "data")
P = str(_DATA / "processed" / "dashboard_bulk_gazette_2026-07.parquet")
R = str(_REPO / "dashboard" / "post_build_change"
        / "shortlist_reasons_2026-07.parquet")
API = "http://127.0.0.1:8000/api/ranking?model="

MODELS = [("lending", "score_lending"), ("insolvency", "score_insolvency"),
          ("growth", "score_growth")]

con = duckdb.connect()
fails = []


def check(label, ok, detail=""):
    print(("   PASS  " if ok else "   FAIL  ") + label + (("   " + detail) if detail else ""))
    if not ok:
        fails.append(label)


# ---------------------------------------------------------------- the shared denominator
print("== The scored population ==")
scored = con.execute("SELECT count(*) FROM read_parquet(?) WHERE is_active", [P]).fetchone()[0]
universe = con.execute("SELECT count(*) FROM read_parquet(?)", [P]).fetchone()[0]
nullscore = con.execute("""SELECT count(*) FROM read_parquet(?)
    WHERE is_active AND (score_lending IS NULL OR score_insolvency IS NULL
                         OR score_growth IS NULL)""", [P]).fetchone()[0]
check("universe is %s" % f"{universe:,}", universe == 1531094)
check("scored (is_active) is %s" % f"{scored:,}", scored == 1409284)
check("no active company carries a null score", nullscore == 0,
      "so active and scored are the same set")

# ---------------------------------------------------------------- voluntary exit exclusion
print("\n== Why voluntary exit is excluded ==")
for name, col in [("voluntary_exit", "score_voluntary_exit")] + MODELS:
    n_at_cut = con.execute(f"""
        WITH r AS (SELECT "{col}" v, row_number() OVER (ORDER BY "{col}" DESC, CompanyNumber) rk
                   FROM read_parquet(?) WHERE is_active)
        SELECT count(*) FROM read_parquet(?) p
        WHERE p.is_active AND p."{col}" = (SELECT v FROM r WHERE rk = 100)""",
        [P, P]).fetchone()[0]
    if name == "voluntary_exit":
        check("voluntary exit: %d companies share the rank-100 score" % n_at_cut, n_at_cut > 1,
              "-> excluded, a numbered list would invent an order")
    else:
        check("%s: exactly one company holds the rank-100 score" % name, n_at_cut == 1,
              "-> every position 1..100 is earned")

# ---------------------------------------------------------------- per model
for key, col in MODELS:
    print("\n== %s ==" % key)
    api = json.load(urllib.request.urlopen(API + key))
    s = api["summary"]

    truth = con.execute(f"""
        SELECT CompanyNumber, CompanyName, "{col}", sector, segment
        FROM read_parquet(?) WHERE is_active
        ORDER BY "{col}" DESC, CompanyNumber ASC LIMIT 100""", [P]).fetchall()

    # ---- the hundred, position by position
    bad = []
    for i, (cn, name, sc, sector, segment) in enumerate(truth, start=1):
        row = api["rows"][i - 1]
        if row["rank"] != i:
            bad.append((i, "rank", i, row["rank"]))
        if row["number"] != cn:
            bad.append((i, "company", cn, row["number"]))
        if abs(float(sc) - row["rank_score"]) > 5e-7:
            bad.append((i, "score", sc, row["rank_score"]))
        if (row.get("sector") or None) != sector:
            bad.append((i, "sector", sector, row.get("sector")))
        if (row.get("segment") or None) != segment:
            bad.append((i, "segment", segment, row.get("segment")))
    check("all 100 positions match the parquet: rank, company, score, sector, segment",
          not bad, "" if not bad else str(bad[:4]))

    sc = [r["rank_score"] for r in api["rows"]]
    check("scores are non-increasing down the list",
          all(sc[i] >= sc[i + 1] for i in range(len(sc) - 1)))
    check("ranks are exactly 1 to 100, none repeated",
          [r["rank"] for r in api["rows"]] == list(range(1, 101)))
    check("the list is 100 long", api["n"] == 100 and len(api["rows"]) == 100)
    check("the denominator shown is the scored population", api["scored"] == scored)

    # ---- the three headline figures
    t_top, t_bot = float(truth[0][2]), float(truth[-1][2])
    check("score at #1 is %.6f" % t_top, abs(s["top"] - t_top) < 5e-7)
    check("score at #100 is %.6f" % t_bot, abs(s["bottom"] - t_bot) < 5e-7)
    drop = round(100.0 * (1 - t_bot / t_top), 1)
    check("fall between #1 and #100 is %.1f%%" % drop, abs(s["drop_pct"] - drop) < 0.05)

    # ---- the curve is the hundred scores, in order
    check("the curve is the 100 ranked scores in order",
          len(s["curve"]) == 100 and s["curve"] == sc)

    # ---- counterparty, against the same five predicates the LBG filter uses
    cp = con.execute(f"""
        WITH t AS (SELECT * FROM read_parquet(?) WHERE is_active
                   ORDER BY "{col}" DESC, CompanyNumber ASC LIMIT 100)
        SELECT count(*) FILTER (WHERE is_lbg_client),
               count(*) FILTER (WHERE ever_lbg_client AND NOT is_lbg_client),
               count(*) FILTER (WHERE NOT ever_lbg_client AND n_competitor_lenders > 0),
               count(*) FILTER (WHERE NOT ever_lbg_client AND n_competitor_lenders = 0
                                AND n_charges_outstanding > 0),
               count(*) FILTER (WHERE NOT ever_lbg_client AND n_competitor_lenders = 0
                                AND n_charges_outstanding = 0),
               count(*) FILTER (WHERE gaz_matched = 1)
        FROM t""", [P]).fetchone()
    shown = [x["n"] for x in s["counterparty"]]
    check("counterparty split recomputes: %s" % (list(cp[:5]),), list(cp[:5]) == shown)
    check("counterparty sums to 100 (the five buckets partition the hundred)", sum(shown) == 100)
    check("gazette count recomputes: %d" % cp[5], cp[5] == s["gazette"])

    # ---- segment, including the tie-break that makes it a total order
    segs = con.execute(f"""
        WITH t AS (SELECT * FROM read_parquet(?) WHERE is_active
                   ORDER BY "{col}" DESC, CompanyNumber ASC LIMIT 100)
        SELECT coalesce(segment, 'Not stated'), count(*)
        FROM t GROUP BY 1 ORDER BY 2 DESC, 1 ASC""", [P]).fetchall()
    check("segment mix recomputes, in the same order: %s"
          % " ".join("%s %d" % x for x in segs[:3]),
          [(x["k"], x["n"]) for x in s["segment"]] == [(a, b) for a, b in segs])
    check("segment counts sum to 100", sum(x["n"] for x in s["segment"]) == 100)

    # determinism: the tie-break has to survive repeated calls
    orders = set()
    for _ in range(4):
        again = json.load(urllib.request.urlopen(API + key))
        orders.add(tuple(x["k"] for x in again["summary"]["segment"]))
    check("segment order is stable across 4 calls", len(orders) == 1)

    # ---- every ranked company is inside the SHAP extract, so none shows the empty state
    quoted = ",".join("'%s'" % r["number"] for r in api["rows"])
    hit = con.execute(f"""SELECT count(DISTINCT CompanyNumber) FROM read_parquet(?)
                          WHERE target = ? AND CompanyNumber IN ({quoted})""",
                      [R, key]).fetchone()[0]
    check("all 100 carry SHAP drivers", hit == 100)

    # ---- the claim printed under the curve
    inband = con.execute(f"""
        WITH t AS (SELECT "{col}" v FROM read_parquet(?) WHERE is_active
                   ORDER BY "{col}" DESC, CompanyNumber ASC LIMIT 100)
        SELECT count(*) FROM t WHERE (SELECT count(*) FROM read_parquet(?) p
              WHERE p.is_active AND p."{col}" > t.v) * 100.0 / {scored} <= 1""",
        [P, P]).fetchone()[0]
    check("all 100 sit inside the population's top 1%%, as the note claims", inband == 100)

print("\n" + ("ALL RANKING CHECKS PASSED" if not fails
              else "FAILURES: %d -> %s" % (len(fails), fails)))
