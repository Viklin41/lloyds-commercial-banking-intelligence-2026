# Post-build changes

Changes made to the dashboard after the build described in `dashboard_design.md` and the decision
record in `FILTER_SPEC.md` closed. Those two documents describe the system as it was specified and
built; this one records everything that has happened to it since, so that neither goes stale silently.

Newest first. Every entry answers the same five questions:

- **What was wrong** — the observed problem, not the fix
- **What changed** — files and specifics, enough to find it again
- **What it does now** — the behaviour after the change
- **What we were missing before** — what the old behaviour cost, which is the part that is easy to
  lose once a fix looks obvious
- **How it was verified** — evidence, not assertion

Status is one of **done** (applied and verified), **pending** (applied but waiting on a decision or a
person), or **reverted**.

---

## 2026-08-28 · The identity source: 639 MB CSV to a 27 MB parquet

**Status:** done

**What was wrong.** `serve.py` read `filtered_bb_sme_sectors_all_status_2026-08-01.csv` at every
startup for exactly four fields: incorporation date and the three address lines. The file is **639 MB,
58 columns, and untyped**, because it is read `all_varchar=true`. Fifty-four columns were being parsed
and discarded once per restart, and it was by a wide margin the largest thing the dashboard touched.

**What changed.** `post_build_change/build_identity_parquet.py` writes the same table, already cleaned
and already deduplicated, as a parquet. The SELECT it runs is character-for-character the one
`load_aux()` was running, so the result cannot differ by construction: same cleaner, same `QUALIFY`,
same column names. `serve.py` now prefers `identity_2026-08-01.parquet` and falls back to the CSV, so
a checkout without the parquet still works, just slower.

**What it does now.**

| | Before | After |
|---|---|---|
| On disk | 639 MB | **26.8 MB** (24x smaller) |
| Load time | 2.9s | **0.14s** (21x faster) |
| Columns parsed | 58 | 5 |

**What we were missing before.** Nothing on screen: this is the same data. What it cost was about
three seconds of every restart and 639 MB of the data tree, for four fields. On a dashboard whose whole
architecture is built on not moving data around unnecessarily, the largest file it read was the one
doing the least work.

**How it was verified.** Not by sampling. The build script materialises both the CSV path and the
parquet path and runs a full `EXCEPT` **in both directions**: 1,496,693 rows each side, **0 rows
present in one and not the other**, identical column names and order, key unique with no nulls. After
the switch, `ident` still loads 1,496,693 rows, five companies spot-checked against the source CSV
match on all three identity fields, and the standing suites all pass: 55 ranking checks, the model
panel provenance audit, nine of nine presets, and the three existing views at their populations.

**Re-run it** whenever the source CSV is refreshed:
`python dashboard/post_build_change/build_identity_parquet.py`

---

## 2026-08-26 · Model rankings: verification pass and interface refinement

**Status:** done

A full re-verification of the ranked view against the parquet, and five interface changes on
top of it. Two of the five were defects rather than polish.

### The ranking logic, stated once

| Model | Column |
|---|---|
| Lending | `score_lending` |
| Insolvency | `score_insolvency` |
| Growth | `score_growth` |

- **Population**: `is_active`. No active company carries a null score, verified, so active and
  scored are the same 1,409,284 rows and the denominator on screen is honest.
- **Order**: the chosen score **descending**.
- **Tie-break**: `CompanyNumber` ascending, matching `TIE_BREAK` everywhere else in the server.
- **Rank**: `row_number()` over exactly that ordering, cut at 100. The rank comes from the same
  window that orders the rows, so the number beside a company and its position in the list
  cannot disagree.
- **Voluntary exit is excluded** because **138 companies share its rank-100 score**. Positions
  100 to 237 would be one arbitrary tie-break apart, and a numbered list would be asserting an
  order the data does not contain. For the other three, exactly one company holds the rank-100
  score, so every position from 1 to 100 is earned. All four figures are re-measured by the
  verification script rather than quoted.

### Verification

`post_build_change/verify_model_rankings.py`, run with the server up. Ground truth is written
from the column semantics, not lifted from `serve.py`. **55 checks, all passing.**

Per model, recomputed from the parquet:

- all 100 positions: rank, company number, score, sector and segment
- scores non-increasing down the list; ranks exactly 1 to 100, none repeated
- the denominator shown equals the scored population
- score at #1 and at #100, and the percentage fall between them
- the curve is the 100 ranked scores, in order
- the counterparty split, and that its five buckets sum to exactly 100
- the Gazette count
- the segment mix **and its ordering**, plus stability across four consecutive calls
- that all 100 carry SHAP drivers, so no company reachable from this view shows the empty state
- that all 100 sit inside the population's top 1%, which is the claim printed under the chart

| | lending | insolvency | growth |
|---|---|---|---|
| #1 | 0.577182 | 0.477896 | 0.513887 |
| #100 | 0.355634 | 0.170421 | 0.280031 |
| fall | 38.4% | 64.3% | 45.5% |
| counterparty | 9 / 10 / 70 / 11 / 0 | 1 / 3 / 3 / 0 / 93 | 10 / 13 / 62 / 4 / 11 |
| top segment | Large 40 | Micro 76 | Medium 41 |
| Gazette | 1 | 5 | 0 |

### 1. The model selector was visible when it should not have been

**A defect, not a preference.** `.rankseg` carries `display:flex`, which beats the user-agent
`[hidden]` rule, so setting the attribute did nothing and the three model chips sat under the
Views control at all times. This is the same omission that had left the Tools block visible in
this view, found again in a second place.

**Fixed with `.rankseg[hidden]{display:none}`**, and the interaction chosen deliberately between
the two options offered. **Reveal on selection, not a chevron.** The Views control is a
segmented control with a sliding marker: a chevron on one segment breaks that symmetry and
implies the other three could expand too. It also implies the choices could be opened without
selecting the view, which is not a state that means anything, since the models only exist once
the ranking is active.

To make them read as subordinate rather than as a fourth independent control, they are indented
under the chip, hung off a mint rule, prefixed with a small `MODEL` eyebrow, and animated in.

### 2. The transition into the view

The ranking does more work than a page of browse, and the old behaviour was to clear the list,
sit empty, then drop the whole section in at once. A skeleton now goes up immediately at the
finished height: two summary boxes and six row placeholders, with the existing shimmer language
and the existing `.rise` animation on the content that replaces them.

**The height jump was measured rather than eyeballed.** The first attempt still moved the page
117px, because the skeleton's `min-height` was 250 and the loaded section 367. `min-height` is
now 384: skeleton 384, lending 384, insolvency 384, growth 389. The 5px is growth carrying a
fifth counterparty row.

### 3. The two summary cards now align

They were two boxes beside each other with different content volumes, forced to equal height by
the grid and leaving a pocket of dead space in the left one. Both are now flex columns with a
`.rs-body` that takes the slack, so the heads sit on one line, the notes sit on another, and the
chart takes whatever is left. Measured equal at 367px on lending.

### 4. The chart

The zero floor stays, and that was the constraint worth defending: scaling to the visible range
would turn a shallow fall into a cliff, which is exactly the distortion ruled out. What was added
is information rather than amplification:

- **the first ten shaded**, with a dashed divider. A call list is worked from the top, so where
  the strongest scores sit is a fact about how to use the list.
- **the endpoints labelled on the plot**, so #1 and #100 are read off the curve rather than only
  from the figures above it.
- a fourth gridline at the top of the scale, and a heavier stroke.

### 5. The Quick Look panel, and a metric that was being thrown away

It led with five numbers to compare. It now leads with the fact: **62 of 100 borrowing
elsewhere**, because that is what changes what a banker does with the list. The bar is heavier,
size became bars rather than a column of counts, since on insolvency the shape (76 Micro of 100)
is itself the finding.

**The Gazette count was already being computed by the API and never displayed.** It is now the
footer line: *1 of the 100 also carry a Gazette notice* on lending, 5 on insolvency, and on
growth the honest negative, *None of the 100 carries a Gazette notice*. No metric was invented to
fill the panel out.

### 6. The summary cards were a second card language, and now are not

**What was wrong.** `.rs-card` was a hand-rolled surface: a background, a border and a radius
that resembled the Market Analytics cards without being them. It sat outside the shared card
block at the foot of the stylesheet, the one whose comment says "every card on the dashboard
now shares" it, so it had **no specular catch, no ambient glow, no rim warming and no hover
lift**. Next to the rest of the dashboard it read as a panel from a different product.

**What it does now.** Both summary cards are built by `maCard()`, the same function every
Market Analytics card uses. They are `.ma-card.ma-card--compact` and therefore carry the whole
anatomy without restating any of it:

| Part | Now shared |
|---|---|
| Surface, radius, light, hover | the `:is(.ma-card, .panel, ...)` block |
| Header | `.ma-head` with `.ma-ico`, `.ma-t`, `.ma-m` |
| Figures | `.ma-metrics` with `.ma-k` / `.ma-v` and the mint accent |
| Chart slot | `.ma-plot`, taking the slack so the two cards align by construction |
| Conclusion | `.ma-take` with its icon |
| Explanation | `.ma-info` and `.ma-reveal`, the same tap-to-pin mechanism |

The three headline figures became a proper metric strip rather than a bespoke row, and the
dominant counterparty and the Gazette count became the second card's two metrics. Only the row
proportion is new: `.ma-row--rank`, following `.ma-row--lead`'s precedent of a named variant
rather than an inline style. Every bespoke class from the first version is gone.

**A consequence worth noting.** Because `.ma-plot` takes the slack inside a flex column, the two
cards now align by construction rather than by a min-height that had to be guessed. Growth
carries five counterparty rows against lending's four and still measures identically.

**The skeleton had to be re-measured.** Rebuilding on `maCard` changed the loaded height from
367 to 521, and the placeholder was still 372, so the section jumped 149px. Both are now 521:
skeleton 521, lending 521, insolvency 521, growth 521. Zero movement.

### 7. Trimmed back after seeing it: asides out, icons out, height down

**The takeaway asides went.** Each card ended in a bordered box with its own icon carrying one
sentence, which gave a remark the visual weight of a section. Both are now plain text inside the
card. The `.ma-take` component is untouched and still used by the analytics cards, where a card
is a page's worth of chart and the aside earns its border.

**The header icons went too**, scoped to this row only. `maCard` always draws one and changing
that signature would reach every analytics card, so the rule is `.ma-row--rank .ma-ico
{display:none}`. Confirmed not to leak: all 11 Analytics cards still render their icons.

**A CSS defect found while shrinking the cards.** `.rs-curve` was set to `height:100%` inside a
parent with automatic height. A percentage against an auto-height parent resolves to auto, and an
SVG with a `viewBox` and no height then falls back to its aspect ratio: the 100x40 box at 700px
wide was claiming **276px** of curve and setting the height of *both* cards, while the
`min-height` written next to it never bound at all. Pinned to an explicit 126px.

**Height, measured rather than guessed.** 521 to **398**, a 24% reduction. 398 is the natural
height of the tallest model, growth with five counterparty rows; lending and insolvency are 377
and are held to the same box so switching model does not resize the section. The skeleton uses
the same number, so skeleton, lending, insolvency and growth all measure 398 and the section
never moves. The size list also went from four rows to three.

### 8. Reading the curve: hover, and the two ideas that were rejected on the data

**What was added.** Every point on the curve is a company, so hovering one names it. A mint
guide and a marker follow the pointer, and a card gives rank, company, score, size and
counterparty; clicking opens that company's profile with the ranking carried across as the
match context. The marker and the guide are DOM rather than SVG, because the plot is drawn
`preserveAspectRatio="none"` and a circle would be stretched into an ellipse.

`counterparty` now travels on each ranked row from the server, derived from the same five
predicates as the summary bar and the LBG relationship filter. Deriving it a second time in the
browser is how the tooltip and the bar would come to disagree; verified they tally exactly
(70 / 9 / 10 / 11 on lending, both ways).

**Two richer ideas were measured and rejected**, which is the part worth recording.

**Overlaying the other model scores** is not honest at true scale. Across the lending top 100
the medians are lending **0.402**, growth **0.028**, insolvency **0.018**, voluntary exit
**0.0008**. On a shared zero-based axis the other three are flat lines on the floor; making them
visible would require normalising each to its own range, which is the distortion this chart
already refuses, and would make an 0.018 insolvency score look the equal of a 0.40 lending one.

**Colouring the curve by counterparty** would look like the reference and carry nothing. By
decile down the lending hundred, "borrowing elsewhere" runs 9, 8, 7, 7, 5, 5, 8, 8, 6, 7 and
"current client" is 1 in nine deciles out of ten. On insolvency, "no charge ever" runs 10, 10,
10, 10, 10, 9, 10, 7, 8, 9. **The variable does not vary with rank**, so the colour would be ink
rather than information. Segment is nearly as flat; the only real signal is that the top decile
of lending is Large-heavy, 8 of 10, and the size bars already say so.

**On accessibility.** The chart stays `aria-hidden`. The hundred ranked cards below it are the
accessible path to every one of these companies, and duplicating them into a hundred focus stops
inside an SVG would make the page worse for a keyboard user, not better.

### How it was verified

- Probed at the left edge, the middle and the right: #1 MS LENDING GROUP LIMITED at 57.72%,
  #51 GREEN MARINE (UK) LIMITED at 40.18%, #99 OSTEREO LIMITED at 35.81%, each with its size
  and counterparty.
- **The marker sits on the line, not near it**: at #1 it renders at 6.3px against a path
  geometry of 6.3px, and at #99 at 49.35px against 49.35px.
- The card flips to the left of the pointer near the right edge rather than being clipped.
- Hovering then clicking #29 opened TUPRAS TRADING LTD with its score panel and SHAP drivers.
- Per-row counterparty tallies equal the summary bar exactly.
- No console errors; the readout clears on pointer leave.
- No `.ma-take` survives in the ranking row; both closing lines render as plain text.
- The header icons compute to `display: none` in the ranking row and remain visible on all 11
  Analytics cards.
- Skeleton, lending, insolvency and growth all measure 398px.
- Both cards are `.ma-card.ma-card--compact` and carry `.ma-head`, `.ma-ico` with an svg,
  `.ma-info`, `.ma-metrics`, `.ma-take` and `.ma-reveal`.
- The shared surface is present: 16px radius, the standard rim, and the `::before` light layer.
- Skeleton and all three models measure 521px, so the section does not move at any point.
- No bespoke ranking card class survives anywhere in the file.
- The selector is `display: none` before selection and `flex` after, with the eyebrow present.
- The skeleton renders two summary boxes and six row placeholders within 120ms of the click.
- Summary height across skeleton and all three models: 384 / 384 / 384 / 389.
- Both summary cards measure equal.
- Endpoint labels, four size bars, and the Gazette footer all present; no console errors.
- **The full ranking verification re-run after the cosmetic changes: all 55 checks still pass.**
- The model-panel provenance audit still passes; nine of nine presets; all three existing views
  at their populations; the five-way LBG facet still summing to 1,409,284.

---

## 2026-08-26 · Model rankings: a fourth starting point on Home

**Status:** done

The ranked view that was in the original design and never built. It is an ORDER over the
existing spine, not a new dataset: no ranking pipeline, no extra file, no new scoring.

### What it is

A fourth chip in Views, **Model rankings**, which reveals a three-way selector, **Lending ·
Insolvency · Growth**. Choosing one replaces the list with the top 100 companies on that score,
each carrying an explicit position from #1 to #100, above a compact summary of what that hundred
is made of. The card, the click and the profile are the ones the other views use, unchanged.

### Why voluntary exit is excluded, with the measurement

Not editorial. **138 companies share the rank-100 voluntary exit score**, so positions 100
through 237 would be one arbitrary tie-break apart and a numbered list would be inventing an
order the data does not have. For the other three, exactly one company holds the rank-100 score,
so every position from 1 to 100 is earned.

### Why a route rather than a fourth entry in VIEWS

Viktor's route was to add three views and sort on the score columns, which are already in
`NUMERIC_FILTERS` and therefore `SORTABLE`, with `/api/browse` already honouring `sort` and
`dir`. That reading of the plumbing is correct and the ranking uses exactly those columns.

It is served from `/api/ranking` rather than added to `VIEWS` for one reason: a member of
`VIEWS` is a WHERE clause, and it is consumed by the facet endpoint, the presets and the
watchlist as well as by browse. A ranking is an ORDER and a cut at 100, which is a different
kind of thing. Adding it there would have changed facet counts that are verified elsewhere, and
`total` would have read 1,409,284 under a heading saying Top 100. The route keeps the existing
views provably untouched, which was a requirement of the change.

Rank is produced by the same window that orders the rows, `row_number() OVER (ORDER BY score
DESC, CompanyNumber ASC)`, so the number beside a company and its position in the list cannot
disagree. The tie-break matches `TIE_BREAK` everywhere else. The population is `is_active`: no
active company has a null score, so active and scored are the same 1,409,284 and the denominator
on screen is honest.

### The summary above the list, and why these two things

The brief left the choice of chart open, so it was made from the data. Both blocks earn their
place by differing sharply between models:

|  | lending | insolvency | growth |
|---|---|---|---|
| Counterparty | 70 borrowing elsewhere | **93 no charge ever** | 62 borrowing elsewhere |
| Segment | Large 40, Small 31 | **Micro 76** | Medium 41 |
| #1 to #100 | 0.577 to 0.356, **38.4% fall** | 0.478 to 0.170, **64.3%** | 0.514 to 0.280, **45.5%** |

**The score curve** answers the question a banker has before reading any name: does position
matter here, or is the hundredth company much like the first? A 38% fall says work it top down.
It is drawn against a zero floor rather than against the visible range, because scaling to the
range would stretch a shallow fall into a cliff. It also carries the fact that makes the rank
necessary at all: **all 100 sit inside the population's top 1% on every model**, so the band
chip cannot separate them and only a position can.

**The counterparty split** says which team the list belongs to. A lending hundred that is 70%
borrowing elsewhere is a Growth list; an insolvency hundred that is 93% never-charged is not a
lending conversation at all. It uses the same five predicates as the LBG relationship filter, so
the two cannot tell different stories. Size sits under it as the secondary cut.

Sector was measured and dropped: it is close to the population mix on two of the three models
and adds little a banker would act on.

### Filters and presets are hidden in this view

Both narrow a population. A ranking is a fixed hundred, so leaving them live would quietly
produce a list that is no longer the top hundred of anything. The Tools block and its label are
hidden for the duration and restored on the way out, and the facet endpoint is not called at
all: `rank` is not a member of `VIEWS`, so asking it for facet counts is a 400 by design.

### A defect found and fixed during verification

The segment strip ordered on `count(*) DESC` alone, which is not a total order. On lending,
**Dormant and No Filings both hold 4 and swapped places between successive calls** to the same
endpoint, so the strip reordered itself under the reader. This is defect B1 from `FILTER_SPEC`
in a smaller costume. Fixed with a name tie-break, `ORDER BY 2 DESC, 1 ASC`, and confirmed stable
across four consecutive calls. It was the verification that caught it, not the eye: the display
only shows the top three rows, where the tie never appeared.

### Files

- `serve.py` — `RANK_MODELS`, `RANK_N`, and the `/api/ranking` route
- `index.html` — `RANK_VIEW` state and the model selector; `rankCurve()`, `rankSummary()` and
  `paintRanking()`; the ranked-card grid; the ranking CSS; `paintPanel` and the Tools block
  guarded

### How it was verified

Ground truth written from the column semantics rather than lifted from `serve.py`, for all three
models:

- **All 100 positions match the parquet**, company for company and score for score.
- Scores are non-increasing down the list, and ranks are exactly 1 to 100 with none repeated.
- Counterparty counts, segment mix and the fall figure all recompute from the parquet.
- **All 100 of every top 100 carry SHAP drivers**, since the hundred sits inside Viktor's top
  5,000, so no company reachable from this view shows the empty driver state.
- Clicking #3 opens CASTLE AIR LIMITED with its model panel and drivers intact.
- Switching models repaints; returning to All companies restores the tools, the filter panel
  (30 groups) and the 25-row list.
- Nothing else moved: nine of nine presets, all three existing views at their populations
  (1,531,094 / 19,525 / 14,416), the five-way LBG facet still summing to 1,409,284, and the
  model-panel provenance audit still passing end to end.

One artefact worth recording so it is not mistaken for a finding: the verification script's
"companies on #100 score" reads 0 because it compares the API's 6dp-rounded score against
full-precision parquet values. At full precision it is 1 for all three models, which is the
check that matters and which is reported above.

---

## 2026-08-26 · Model scores panel, third pass: containers, band colour, and a disclaimer that was wrong

**Status:** done

Four fixes after review. The fourth is a correction of substance rather than presentation.

### 1. The close button sat behind its own reveal

The reveal is `z-index: 6` and the toggle had none, so opening the panel covered the control
that dismisses it. The button is now `position: relative; z-index: 7`. Verified with
`elementFromPoint` at the button's centre while the reveal is open: the button is the topmost
element.

### 2. Each model is a container

With a percentage, a three-figure strip and three drivers in every one, a 1px underline was no
longer enough to tell where one model ended and the next began. Each model is now a bordered,
rounded container with its own background, and the rules above the stat strip and above the SHAP
block went from 6 to 8% opacity to 14%.

**Two clipping defects caught by measuring rather than looking.** Adding 12px of horizontal tile
padding cut the stat strip from 285px to 259px and re-clipped the values; then fixing the values
left the label `PRECISION @100` clipping. Fixed by removing "in 100" from the precision value,
where it duplicated the label, and by giving that column the slack (`flex: 1.25`) with a smaller
label size. Re-measured across all twelve cells and all four models: nothing clips.

### 3. Band colour now means something

**What was wrong.** The band chip was mint whatever it said, so "Lower half" looked as
affirmative as "Top 1%".

**What it does now.** Top 1% and Top 5% keep the mint; Top 10% and Top 25% go neutral; anything
below is amber.

**The judgement call, stated because it is arguable.** Colour encodes **how far up this model's
list the company sits, and nothing else**. It is deliberately not a good/bad axis, because the
four models do not share one: a high lending or growth score is an opportunity, while a high
credit risk or voluntary exit score is a warning. Amber on voluntary exit therefore means "this
model does not single the company out", which is good news, not bad. The panel says so in the
Read more, because a colour that means two things without saying which is worse than no colour.

### 4. The panel disclaimer was making a false claim

**What was wrong.** The footnote read "...approximately right through the middle of the range and
as a ranking near the top, where it runs optimistic". The second half is wrong, and wrong for the
model the panel leads with.

Q1's band table in `meeting-answers-2026-08-25.md` gives observed over predicted by score band.
For lending it is **1.21** in the 0.40 to 0.50 band and **1.12** above 0.50: observed *exceeds*
predicted, so at the very top lending runs low, not high. The claim holds for insolvency and
growth and inverts for lending, which is exactly where the shortlist lives.

The old wording also called the number "raw". It is not: the shipped column has been through
`recalibrate`, and "raw" implies untreated model output. The inline label beside each score now
reads `score 0.2630` rather than `raw 0.2630`.

**What it says now**, four sentences, claiming no direction of error at the top:

> Forecasts about the windows shown, not descriptions of July. The score is an estimated
> probability corrected back to the true base rate, and it tracks well through the middle of the
> range. Near the top of the list there are too few past cases to check it, so read the band
> rather than the digits.

**What moved behind a Read more.** Three paragraphs that a reader deciding whether to make a call
does not need in front of them: what the band colour means, the scored population and the tie
convention, and the calibration evidence (mean 0.00301 against an observed 0.00271 for lending;
0.00363 against 0.00329 for insolvency; and only ten held-out lending rows, two insolvency and
two growth, ever landing above 0.5, which is why the extreme top cannot be checked).

**A stale code comment corrected too.** The header comment above the model-scores block still
instructed "never the word probability" and repeated the runs-optimistic claim. Both are now
wrong, and the comment says what is actually enforced instead.

**Amended the same day.** The three Read more paragraphs were cut and the four-sentence
disclaimer moved into the Read more in their place, so nothing sits outside the four model
tiles but the button itself. Of the three, only the band-colour explanation carried anything the
panel still needed, and it moved onto the chip as a tooltip: *"This model does not place the
company near the front of its list"*. The scored-population and tie-convention paragraph and the
calibration-evidence paragraph were dropped outright. Nothing of Viktor's correction was lost
with them: his four claims are all answered by the disclaimer's own wording, which asserts the
score is an estimated probability corrected to the base rate, states that it tracks through the
middle of the range, and declines to claim a direction of error at the top. The evidence
paragraph was support for that wording rather than a claim of its own.

### One figure I could not verify

Viktor's note quotes top-100 lending as predicted 0.447 against observed 0.550. That pair does
not appear in `meeting-answers-2026-08-25.md` and is not reproducible from anything in the
repository, so it is not used anywhere on screen. The claim it supports, that lending runs low
rather than high at the top, **is** supported by the band table that is in the document, and that
is what the wording rests on.

### How it was verified

- The toggle is the topmost element at its own centre while the reveal is open.
- Band chips: a company low on all four renders four amber chips (`rgb(240,192,120)`); a company
  in the top 1% renders mint. The unranked tile's amber needed a specificity fix, since
  `.scorerow.unranked .bandchip` outranked `.bandchip.weak`.
- Read more toggles the block and the label, and starts closed.
- No stat label or value clips in any of the twelve cells.
- The provenance audit re-run end to end: **ALL CHECKS PASSED**.
- Nine of nine presets at their expected populations; the five-way LBG facet still 1,409,284 on
  Trading.

---

## 2026-08-26 · Model scores panel, second pass: provenance audit and five interface fixes

**Status:** done

Follows the entry below. Five changes after review, plus a full audit of where every number on
the panel comes from.

### The provenance audit

Every figure the panel puts on screen was traced to a source, on 175 companies: 150 drawn at
random from the reasons file and 25 with no reasons at all, to exercise the absent path.

| Class | Source | Checks | Result |
|---|---|---|---|
| Score, percentile band | company parquet | 700 | **0 mismatches** |
| Driver feature, log-odds, weight, direction, value | reasons parquet | 468 each | **0 mismatches** |
| Precision, base rate, lift | `store_meta.json` | 4 models | matched to source document |
| Coverage block (18,644 / 5,000 / 3 / 0.35%) | `store_meta.json` | 5 | recomputed from the parquet |
| Feature labels | `serve.py` | 30 | every feature in the file is labelled |

**The distinction that matters.** Precision, base rate and lift are **not in either parquet and
cannot be**: they are held-out evaluation metrics measured against realised outcomes on past
origins. They were therefore checked against the Q5 table in
`post_build_change/meeting-answers-2026-08-25.md` by parsing that table programmatically, and
all four models agree on base rate, P@100 and lift ranges, with every `lift_about` falling
inside its own measured range. The honest description of those three numbers is "traced to the
source document", not "verified against the data". Everything else on the panel is verified
against the data. The audit script is `scratchpad/audit.py`.

### 1. The panel names SHAP

The drivers heading is now **"SHAP analysis · what drives this score"** rather than "What drives
this score". The method was previously implied.

### 2. The info button flickered and would not stay open

**What was wrong.** The reveal opened on `:has(.scoreinfo:hover)` as well as on click, copied
from the Market Analytics cards. That works there because the reveal covers a wide card the
pointer can move into. Here the trigger is a 20px circle with the reveal directly beneath it, so
any small movement dropped the hover and closed the panel, and it could only be held open by
keeping the pointer on one exact spot.

**What it does now.** Click only. The hover selector is gone, so nothing but the button opens
it. The glyph toggles **i** to **×** and the tooltip toggles with it, so the control states
whether it is open rather than leaving the reader to infer it from a panel that may be scrolled
out of view. Clicking the reveal still closes it.

### 3. Precision, base rate and lift are on the tile, not behind the button

**What was wrong.** All three sat inside the reveal. A number a reader must open a panel to find
is a number badly placed, and it made the reveal long enough that few would read it.

**What it does now.** A three-column strip under the score, in the same divided form the Market
Analytics cards use for their metrics:

```
BASE RATE        PRECISION @100     LIFT
0.26 to 0.28%    41 to 43 in 100    ~150x
```

The label says `@100`, so the scope is on the tile rather than only in the caveat.

**A layout defect caught in the process.** At the panel's 285px width, `0.26% to 0.28%` and
`7.22% to 8.24%` both clipped. The repeated per-cent sign was the cause; the low bound now
carries no sign and the value font is 11.5px. Re-measured: no value in any of the twelve cells
clips.

### 4. The reveal is now two sentences

**What was wrong, and it was a fair question to ask of it.** The reveal held roughly 140 words,
of which only the log-odds line was specific to the company being viewed. The two performance
paragraphs were per-model constants, identical on every company page for that model. It read as
personalised explanation and was not.

**What it does now.** Everything factual moved onto the tile, and what remains is two caveats,
about 60 words:

> Base rate, precision and lift describe the **top 100 companies by this score**, not this
> company. Measured across two held-out origins and given as a range rather than the better of
> the two.
>
> SHAP weights are each driver's share of **this company's own three contributions**, not a
> share of the score. Raw log-odds: +3.2495, +0.9942, -0.3574, which are additive in log-odds
> and must not be summed against the score.

The log-odds line is the only company-specific content, and it is now the only thing in there
that needs to be.

### 5. Absence is one line, not a paragraph

**What was wrong.** A company outside the extract got a three-line explanation of the extract's
coverage, in a panel where three of four tiles will usually say it. The explanation was right and
the placement was not.

**What it does now.** A single amber chip: **No SHAP analysis available**. Amber rather than red,
because this is a gap in our coverage, not a fault and not a finding about the company. The
reason stays one click away in the reveal, which every tile carries: *SHAP reasons were computed
for the top 5,000 companies on each model separately. A company can be in one model's extract
and not another's.*

That preserves the rule from the first pass. A bare "none" would read as "nothing drives this
score", which with 0.35% coverage would be wrong on roughly 99.65% of company pages.

### How it was verified

- Hover no longer opens the reveal; click opens it and sets the glyph to ×; a second click
  closes it and restores the i.
- No value in the twelve stat cells clips at the panel's rendered width.
- Both states render: a tile with drivers shows the strip, the SHAP heading and three drivers;
  a tile without shows the strip and the amber chip.
- Nothing else moved: nine of nine presets at their expected populations, the five-way LBG facet
  still summing to 1,409,284 on Trading, and drivers still served on exactly the targets whose
  extracts contain the company.

---

## 2026-08-26 · Model scores panel: percentages, honest performance figures, SHAP drivers

**Status:** done

Three changes to one panel, taken together because they are the same panel and the second is a
correction rather than an addition. Context is the 25 August review call, recorded in
`post_build_change/meeting-answers-2026-08-25.md` (Q1, Q2, Q5, Q8, Q9).

### 1. The score is shown as a percentage

**What was wrong.** The card printed `model score 0.0444`, a bare four-decimal number with no
unit. It read as neither a probability nor a rank.

**What it does now.** The score leads as `4.44%`, with the raw value kept beside it in mono so
the two can be reconciled. The panel disclaimer was rewritten to the sentence agreed at the
call: the percentage is the model's estimated chance of the event inside its window, corrected
back to the true base rate after training, with no calibration curve fitted, so it is
approximately right through the middle of the range and a ranking near the top, where it runs
optimistic.

**What we were missing before.** The old disclaimer said flatly "these are model scores used to
rank, not probabilities". Q1 established that this is too pessimistic: mean recalibrated score
against observed base rate on held-out data is 0.00301 against 0.00271 for lending, and the
decile curve tracks. The number was more informative than the card admitted, and a reader had
no way to know it.

### 2. The precision sentence, which was wrong in a way that mattered

**What was wrong.** Every score row carried the sentence *"43 in 100 at this level went on to
take on new secured borrowing when tested on past months"*. It was built from `m.hit_rate`, a
per-model constant, and never read the company's own percentile. So a company sitting in
**Lower half** on lending was shown "43 in 100 at this level" directly beneath a band reading
Lower half. `hit_rate` is precision@100: a property of the top hundred companies and of nothing
else. For a company at the median lending score the true figure is near the base rate, about 1
in 400. **The card overstated it by a factor of roughly 170.**

**What changed.** The sentence moved behind the tile's info reveal and was rescoped:

> Of the **top 100** companies by this score, **41 to 43** went on to take on new secured
> borrowing in the held-out months, against a base rate of **0.26% to 0.28%**. That is roughly
> **150 times** better than picking at random.

with a second line stating that it is measured on two held-out origins, given as a range rather
than the better of the two, and that it describes the top hundred rather than this company.
`store_meta.json` gained `p100_low` / `p100_high`, `base_rate_pct_low` / `base_rate_pct_high`
and `lift_low` / `lift_high` / `lift_about` per model, from the per-origin table in Q5. The old
`hit_rate` and `lift` keys are retained but no longer read, and are marked superseded.

**What we were missing before.** Three things. The figures shown were **the better of the two
held-out months** in every case (lending 0.43 where the months are 0.43 and 0.41; voluntary
exit 0.85 where they are 0.85 and 0.78), with nothing on screen saying so. The lift constant,
160 for lending, **matched no measurement**: the per-origin lifts are 167 and 144. And the base
rate was absent entirely, which is the number that makes precision readable at all: voluntary
exit's 78 to 85 in 100 looks extraordinary until its 8% base rate shows the lift is 10x, the
same as growth.

Pooled figures were considered and rejected. Pooled precision falls outside the range of its own
months in 5 of 8 target-metric pairs, and flatters lending worst: pooled P@100 of 0.55 against
months of 0.43 and 0.41.

### 3. SHAP drivers per model category

**What was added.** `shortlist_reasons_2026-07.parquet`, loaded as a side table alongside the
Gazette, news, property, trade mark and grant packs. Each model tile now shows what drove that
company's score for that model.

**What the file actually contains**, verified against it rather than taken from the handover
note:

| Property | Verified |
|---|---|
| Rows | 60,000 = 4 targets x 5,000 companies x 3 reasons |
| Grain | unique on (CompanyNumber, target, rank_within_reason); every pair has exactly 3 |
| Join key | `CompanyNumber` **and** `target` |
| Key match | all 18,644 distinct companies match the spine on the raw 8-character key, 0 unmatched |
| Overlap | 17,368 companies in one target only, 1,196 in two, 80 in three, none in four |
| Cut | the true top 5,000 by score for lending, insolvency and growth; 4,995 for voluntary exit, whose tie band at the cut is the known ties problem, not a defect |
| Coverage | 0.35% of the 1,409,284 scored companies |

**Two data problems found before implementing, either of which would have shipped nonsense:**

- **10.15% of rows carry the literal string `"nan"`** in `value`: `months_since_last_confstmt`
  4,681 rows, `tier_rank` 1,357, `months_since_last_accounts_filing` 52. By target, at least one
  unusable value affects **4,683 of voluntary exit's 5,000 companies**, 1,357 of growth's, 61 of
  insolvency's and none of lending's. Printing "nan" beside a driver is worse than printing
  nothing, so the value is suppressed and rendered as *not recorded* while the driver itself is
  still shown: the model did use that feature, we simply cannot state the figure it used.
- **A sentinel of -95669** in `months_since_last_accounts_filing`. Anything beyond a century of
  months is treated as absent.

**Presentation decisions, and why.** The panel is headed **"What drives this score"**, not "why
this company is in your list". For lending the top feature is `Mortgages.NumMortCharges` for
**100.00% of all 5,000 companies** in the extract, and reason 2 is `segment` for 62%; voluntary
exit is worse, with reason 2 being `confstmt_late` for 95%. A "why this company specifically"
label would be answered identically thousands of times over. Growth is the only target where
reason 1 genuinely varies (`tier_rank` 43%, `Mortgages.NumMortCharges` 33%, across 7 features).

Each driver therefore leads with **the feature's value**, not its name, because "578 charges"
against "3 charges" is the actual difference between two companies whose reason 1 is the same
feature. Weights are each contribution as a **share of that company's own three absolute
contributions**, drawn as a bar, with an arrow for direction. The signed log-odds is kept in the
info reveal and never shown inline: three contributions that visibly fail to sum to the score
would invite exactly the arithmetic the report warns against.

**What we were missing before.** The report's routing section states that each row carries its
top three SHAP reasons. Nothing of the kind existed in the dashboard: no SHAP columns in the
parquet, no reference in `serve.py`. The reasons were being computed and then aggregated away
into a global feature ranking before export.

**Absence is handled explicitly.** With 0.35% coverage most company pages have no drivers, and
an empty panel would read as "nothing drives this score". Instead the tile states: *Not in the
driver extract. Reasons were computed for the top 5,000 companies on this model only. This
company is not among them, which says nothing about what drives its score.* The info reveal adds
that a company can be in one model's extract and not another's.

### Files

- `serve.py` — `REASONS` / `REASONS_LOCAL` paths, `FEATURE_LABELS` covering all 30 features,
  `FEATURE_FLAGS`, `FEATURE_MISSING`, `feature_value()`; the `reasons` table in `load_aux()` and
  its row count in the startup report; drivers attached per target in `full_record()`
- `index.html` — tile, reveal and driver CSS; `scorePanel()` rewritten as four tiles each with
  an `(i)` reveal, reusing the Market Analytics `data-note` mechanism; `rangeTxt()` and
  `driverRow()` added
- `store_meta.json` — per-origin performance ranges per model, plus a `reasons` block recording
  the extract's coverage

### How it was verified

- **The join.** A company in the lending extract only receives drivers on lending and none on
  the other three; a company in two extracts receives them on exactly those two. Shares sum to
  100.0% per model.
- **The `nan` path.** 16983519 insolvency renders *not recorded* for
  `months_since_last_accounts_filing` while still listing it as a driver.
- **The negative path.** 12291140 lending shows `segment = Micro` at -0.357 log-odds with a
  downward arrow and an amber bar.
- **Scores unchanged.** API scores compared against the parquet for four companies across all
  four score columns: 0 mismatches.
- **Nothing else moved.** All nine presets return their expected populations; the five-way LBG
  facet still sums to 1,409,284 on Trading; browse returns the full 1,531,094.
- **The interaction.** Four tiles, four info buttons, four reveals; the button pins the reveal
  open and closes it again; the reveal renders the rescoped precision sentence in full.

### Note on the file's location

The parquet currently sits at `dashboard/post_build_change/shortlist_reasons_2026-07.parquet`,
inside the repository. `serve.py` prefers `<data>/processed/shortlist_reasons_2026-07.parquet`
and falls back to the repository copy, so moving it into the data tree needs no code change.
Everything else the dashboard reads lives outside the repository, and this should follow.

---

## 2026-08-26 · Lending readiness window missing its start year

**Status:** done

**What was wrong.** On a company profile, the Model scores panel showed four rows, each with its
horizon and window. Three of them named the year on both sides of the range. Lending readiness did
not:

| Score | Window shown |
|---|---|
| Lending readiness | `Aug to Oct 2026` |
| Credit risk | `Aug 2026 to Jan 2027` |
| Voluntary exit | `Aug 2026 to Jan 2027` |
| Growth | `Aug 2026 to Jul 2027` |

Lending readiness is the only score whose window sits entirely inside one calendar year, so it had
been written in the natural English form. Correct in isolation, inconsistent in a panel where the
other three rows establish the pattern `<month year> to <month year>`.

**What changed.** The window string, in the two places that hold it:

- `store_meta.json` — the configuration the server loads at startup and serves to the browser, so
  this is the file that actually drives the screen
- `build_data.py:91` — the `SCORE_MODELS` definition that regenerates that configuration, changed so
  a rebuild does not reintroduce the old string

Both now read `Aug 2026 to Oct 2026`. No code path, score, or model output was touched: this is a
label.

**What it does now.** All four rows of the Model scores panel carry the year on both sides of the
range and share one date format.

**What we were missing before.** A reader scanning the panel had to infer that the lending window
started in 2026 rather than read it. Because the three rows beneath it print a start year explicitly,
the omission read as missing data rather than as a compact date range, which is the opposite of what
the panel is trying to do everywhere else: state the horizon plainly so a score is never taken as a
standing prediction.

**How it was verified.** `/api/meta` returned all four windows in the new format after restart, and
the change was confirmed on a live profile (ADVANCED INSTRUMENTS LTD., 07284911), where the panel
rendered `Lending readiness · 3 months · Aug 2026 to Oct 2026`.

---

## 2026-08-25 · LBG relationship filter widened from three options to five

**Status:** pending — applied to the working tree, not committed, awaiting Viktor's confirmation

**What was wrong.** The `lbg` filter offered three options: current client, former client, and never a
client. The report's routing section, drafted 8 August, routes the shortlist on a five-way partition
of the universe by lender relationship. The dashboard's "never" bucket silently merged three of those
five:

| Report bucket | Active companies | In the old filter |
|---|---|---|
| Current LBG client | 11,007 | `current` |
| Lapsed LBG client | 13,412 | `former` |
| Borrowing elsewhere, never ours | 64,517 | all three inside `never` |
| Charge held, lender unclassified | 14,651 | |
| No charge ever | 1,305,697 | |

**What changed.**

- `serve.py:96` — the `lbg` choice filter went from three predicates to five, mutually exclusive and
  exhaustive, with a comment recording the reasoning and the verification
- `serve.py` `CHOICE_LABELS` — labels now carry the client's team mapping: *Current client
  (Maintenance)*, *Former client (Attrition)*, *Borrowing elsewhere (Growth)*, plus *Charge held,
  lender unclassified* and *No charge ever*
- `serve.py` preset `prospects_not_banked` — its panel mapping changed from `"lbg": "never"` to the
  three sub-buckets whose union is the same population. Its authoritative `where` clause is untouched,
  so the preset still returns 8,992
- `index.html:3457` — `lbg` joins `gazette` as a genuinely multi-select choice facet. Without this a
  single-select control could not represent the preset's three values

**What it does now.** Advanced filters → Lender → LBG relationship offers five mutually exclusive
options, and any combination of them can be selected. Scoped to Lifecycle = Trading, which is the
population the report quotes, they read 11,007 / 13,412 / 64,517 / 14,651 / 1,305,697.

**What we were missing before.** Two things, and the second is the more serious.

The Growth population was unreadable. Anyone pointing at "never" (1,504,945 on the full universe) as
the set of companies to approach would have been wrong by a factor of more than twenty: the companies
that demonstrably borrow, from someone else, number 64,517.

And the 14,651 companies that hold a charge whose lender the dictionary cannot name were sitting
inside a bucket a reader would interpret as "no bank". That is the taxonomy gap becoming a
client-facing error, which is precisely what the report's routing section says must not happen.

**How it was verified.** Against the parquet, on the active population: every one of the 1,409,284
rows satisfies exactly one bucket, no pair of buckets overlaps (0 of 10 pairwise tests), the five sum
to the population with no remainder, and all four driving columns (`is_lbg_client`,
`ever_lbg_client`, `n_competitor_lenders`, `n_charges_outstanding`) contain no nulls, so no predicate
can evaluate to NULL and drop a row silently. The same holds on the full universe. All nine presets
return their expected populations, and preset B was confirmed at 8,992 both through the API and by
loading it in the browser, where its three facet counts sum to exactly that.

**Breaking change.** `lbg=never` is now rejected rather than silently accepted:

```
{"error":"bad filter value",
 "detail":"lbg: 'never' is not one of ['current','former','elsewhere','unclassified','no_charge']"}
```

Any saved link using it will fail loudly. This is consistent with how `view_where` already handles an
unknown view.

**Open question.** Our bucket counts and the report's differ by a few dozen each (+4, −9, −14, −2,
+21) while the totals match exactly at 1,409,284. An identical total with different membership means
a marginally different boundary rule, not a different snapshot. Ours uses `n_competitor_lenders > 0`
for *borrowing elsewhere* and `n_charges_outstanding > 0` for *lender unclassified*. To be reconciled
with Viktor before either set of figures is quoted.

---

## Still open, not yet started

- **Per-company SHAP reasons.** The report's routing section states that each row carries its top
  three SHAP reasons. Nothing of the sort exists in the dashboard: no SHAP columns in the parquet,
  no reference in `serve.py`. On `origin/sneha-viktor/shap` the models do compute per-row SHAP values
  with `TreeExplainer`, but `train.shap_importance()` collapses them to a global ranking before they
  are written out as `shap_importance_<target>.csv`, which is one feature ordering for the whole model
  and identical for every company. Needs a per-row export keyed on `CompanyNumber`.
- **`dashboard_design.md` lists `data.js` as still 27 MB on disk.** It is not; it was replaced by a
  2.5 KB `store_meta.json`. That open item in the design document is stale and should be closed.
