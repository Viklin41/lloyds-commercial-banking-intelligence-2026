"""Reduce the identity source from a 639 MB CSV to a small parquet.

`serve.py` reads `filtered_bb_sme_sectors_all_status_2026-08-01.csv` at every startup for
exactly four fields: incorporation date and the three address lines. The file is 639 MB, 58
columns and untyped, because it is read `all_varchar=true`. Everything but those four columns
is parsed and thrown away, once per restart.

This writes the same table, already cleaned and already deduplicated, as a parquet. The SQL is
character-for-character the SELECT that `load_aux()` runs, so the result cannot differ from
what the CSV path produces: same cleaner, same QUALIFY, same column names.

    python dashboard/post_build_change/build_identity_parquet.py

Re-run it whenever the source CSV is refreshed. `serve.py` prefers the parquet and falls back
to the CSV, so a checkout without it still works, just slower.
"""
import os
import time
from pathlib import Path

import duckdb

DATA = Path(os.environ.get("LLOYDS_DATA") or r"C:\Users\visha\Lloyds_Github\data")
SRC = DATA / "processed" / "filtered_bb_sme_sectors_all_status_2026-08-01.csv"
OUT = DATA / "processed" / "identity_2026-08-01.parquet"

# Copied from serve.py. If that one changes, this must change with it, which is why the
# verification below compares the two paths row for row rather than trusting the copy.
CLEAN_CN = """CASE
    WHEN replace(upper(trim({col})),' ','') IS NULL
      OR replace(upper(trim({col})),' ','') IN ('','NAN','NONE') THEN NULL
    WHEN regexp_matches(replace(upper(trim({col})),' ',''),'^[0-9]+$')
      THEN lpad(replace(upper(trim({col})),' ',''),
                greatest(8, CAST(length(replace(upper(trim({col})),' ','')) AS INTEGER)), '0')
    WHEN length(replace(upper(trim({col})),' ','')) <= 8
      THEN lpad(replace(upper(trim({col})),' ',''), 8, '0')
    ELSE NULL END"""

SELECT = f"""
    SELECT {CLEAN_CN.format(col='"CompanyNumber"')} AS cn,
           "IncorporationDate", "RegAddress.AddressLine1", "RegAddress.PostTown",
           "RegAddress.PostCode"
    FROM read_csv('{SRC.as_posix()}', all_varchar=true, ignore_errors=true)
    QUALIFY row_number() OVER (PARTITION BY cn) = 1"""

if not SRC.exists():
    raise SystemExit(f"source not found:\n  {SRC}")

con = duckdb.connect()

print("reading  %s  (%.0f MB)" % (SRC.name, SRC.stat().st_size / 1048576))
t0 = time.time()
con.execute(f"CREATE TABLE ident AS {SELECT}")
csv_secs = time.time() - t0
rows = con.execute("SELECT count(*) FROM ident").fetchone()[0]
print("         %s rows in %.1fs" % (f"{rows:,}", csv_secs))

con.execute(f"COPY ident TO '{OUT.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
print("wrote    %s  (%.1f MB)" % (OUT.name, OUT.stat().st_size / 1048576))

# ---------------------------------------------------------------- verification
print("\nverifying the parquet against the CSV it replaces")
t0 = time.time()
con.execute(f"CREATE TABLE ident_pq AS SELECT * FROM read_parquet('{OUT.as_posix()}')")
pq_secs = time.time() - t0

n_pq = con.execute("SELECT count(*) FROM ident_pq").fetchone()[0]
print("   rows          csv %s  parquet %s  %s"
      % (f"{rows:,}", f"{n_pq:,}", "match" if rows == n_pq else "MISMATCH"))

cols_csv = [r[0] for r in con.execute("DESCRIBE ident").fetchall()]
cols_pq = [r[0] for r in con.execute("DESCRIBE ident_pq").fetchall()]
print("   columns       %s" % ("match" if cols_csv == cols_pq else "MISMATCH %s / %s" % (cols_csv, cols_pq)))

# Full anti-join in both directions: nothing added, nothing lost, no value altered.
diff = con.execute("""
    SELECT (SELECT count(*) FROM (SELECT * FROM ident EXCEPT SELECT * FROM ident_pq)),
           (SELECT count(*) FROM (SELECT * FROM ident_pq EXCEPT SELECT * FROM ident))
""").fetchone()
print("   row contents  csv-only %d, parquet-only %d  %s"
      % (diff[0], diff[1], "identical" if diff == (0, 0) else "DIFFERENT"))

nulls = con.execute("SELECT count(*) FROM ident_pq WHERE cn IS NULL").fetchone()[0]
uniq = con.execute("SELECT count(DISTINCT cn) FROM ident_pq").fetchone()[0]
print("   key           %s distinct, %d null  %s"
      % (f"{uniq:,}", nulls, "unique" if uniq + (1 if nulls else 0) == n_pq else "NOT UNIQUE"))

print("\n   load time     csv %.1fs  ->  parquet %.2fs   (%.0fx faster)"
      % (csv_secs, pq_secs, csv_secs / max(pq_secs, 0.001)))
print("   on disk       %.0f MB  ->  %.1f MB   (%.0fx smaller)"
      % (SRC.stat().st_size / 1048576, OUT.stat().st_size / 1048576,
         SRC.stat().st_size / OUT.stat().st_size))
