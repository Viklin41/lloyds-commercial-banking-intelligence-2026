# Client requirements and how the pipeline covers them

Written 26 Jul 2026, at the start of the charges harvest. Until now the client's brief existed only
in conversation: there is no README, no charter file, and no document in this repo that states what
Lloyds actually asked for. That is a gap in its own right, because it means nothing we have built can
be traced back to a requirement in a review. This file fixes that.

## 1. What Lloyds asked for

Three macro areas of their operation, each needing a distinct measure:

1. **Growth.** Add new clients to the portfolio. Companies that do not bank with Lloyds today and
   are about to need something.
2. **Attrition.** Identify clients who are about to move to another provider, and hook them back.
3. **Maintenance.** Offer further services to existing clients, for example risk advisory to a client
   who originally came in for lending.

The framing matters more than it first looks, because all three are defined on the **same axis**:
whether the company is already a Lloyds client. Growth is "not ours". Attrition is "ours, and
leaving". Maintenance is "ours, and staying". They are not three independent questions, they are one
partition of the universe crossed with a need signal.

## 2. Coverage, honestly

| Area | The question | What serves it | Status |
|---|---|---|---|
| Growth | Who will need lending or is scaling, and is not already ours? | Lending Readiness (3m), Growth Signal (12m) | **Need signal: covered. "Not already ours": in progress** |
| Attrition | Which of our clients is about to switch provider? | Lender switching, from the charges harvest | **In progress. Was not covered at all before today** |
| Maintenance | Which existing clients need a different product next? | Credit Risk Exposure (6m) as a risk-advisory trigger | **Partial. No client identity, no product holdings** |
| (Portfolio hygiene) | Which companies are quietly winding down? | Voluntary Exit (strike-off, 6m) | Covered, but see the naming note in section 5 |

The pattern is consistent. **We are strong on predicting what a company will need and weak on knowing
whose client it is.** Every feature in the 33-month panel describes the company: its filings, its
charge counts, its size band, its sector, its contract wins. Nothing describes its banking
relationships. So we can rank 1.37M companies by likelihood of needing credit, but we cannot route
that list to the three teams who asked for it.

## 3. The gap, and what closes it

The missing variable is **counterparty identity**: who holds the company's debt.

The Companies House bulk file gives charge *counts* only (`Mortgages.NumMortCharges`,
`NumMortOutstanding`, `NumMortSatisfied`, `NumMortPartSatisfied`). No lender name, at any point in
the 33 months. The Charges API does carry lender names, in `persons_entitled[].name`.

The useful property is that **charges are append-only and dated**. Every charge carries `created_on`
and, once discharged, `satisfied_on`. So a charge is outstanding at month `t` if and only if
`created_on <= t` and (`satisfied_on` is null or `satisfied_on > t`). One harvest today therefore
reconstructs the whole 33-month lender history retrospectively. No historical downloads, no monthly
re-fetch.

Sneha's `notebooks/04_exiting_relationships.ipynb` reached for exactly this and stopped at
`API_LIMIT = 100`, in-memory, unsaved. Its `LLOYDS_KEYWORDS` list is a good starting point. The one
thing it never read is `satisfied_on`, and that single field is the whole difference between a
snapshot of today's lenders and a replayable panel.

Scale, measured against `data/processed/panel/` rather than estimated:

- Panel universe: **2,038,130** companies. Only **158,684** have ever held a charge (7.8%);
  123,788 ever had one outstanding. That makes a complete harvest a roughly 24-hour single-key pass
  at the Companies House ceiling of 2 requests per second.
- Across the 33 months, **33,041** companies took on a new charge and **26,490** discharged one.
- Inside any rolling 6-month window, **8,133** companies show a refinancing pattern (discharged a
  charge and took a new one), and **22,825** paid one off without replacement.

We harvest everything with at least one charge ever, not just those with an outstanding charge today,
because a company that has paid off its last charge and taken nothing new is precisely an exit
candidate. Filtering on "currently outstanding" would delete the attrition signal we are looking for.

### What it buys, per area

- **Attrition.** `is_lbg_client` at each month, and the switch event itself: the last outstanding
  Lloyds charge discharged, with a competitor charge created nearby. Also `competitor_entered_12m`,
  a new non-Lloyds lender appearing on a previously Lloyds-only company. That one is the *leading*
  indicator, because wallet-share erosion precedes full defection and gives a relationship manager
  lead time that a confirmed-loss signal cannot.
- **Growth.** An outstanding competitor charge and no Lloyds charge means the company is already
  borrowing, from someone else. That is a far sharper prospect list than generic lending readiness,
  and it is a filter rather than another model.
- **Maintenance.** Each charge carries a `classification` and `particulars`, which indicate facility
  type (debenture, legal mortgage, invoice discounting, asset finance). That is the nearest public
  proxy for product holdings, and it is the raw material for next-best-product logic.

## 4. Limits to state out loud

These belong in the client deliverable, not just in a working note.

- **Charges see secured lending only.** Overdrafts, business current accounts, credit cards, merchant
  services and unsecured loans are invisible in public data. Our attrition measure is a proxy for the
  *lending* relationship, not the banking relationship. A client who moves their current account and
  keeps their mortgage will not appear.
- **Only 7.8% of the universe has any charge at all.** For the other 92% we have no relationship
  information whatsoever, so Growth and Maintenance targeting outside the borrowing population rests
  on need signals alone.
- **The switching positive class is thin.** 8,133 companies show a refinancing pattern over 33
  months; applying a realistic Lloyds share of SME secured lending, the true Lloyds-to-competitor
  count is likely in the low thousands. That supports a defensible event feed and a
  competitor-encroachment ranking. It may not support a classifier held to the same precision bar as
  lending. We decide that after measuring, not before, and if it does not hold up we ship the feed
  and say so.
- **Lender names are free text.** `persons_entitled[].name` has no entity resolution, and nominee and
  SPV entries are common. Classification coverage will be reported explicitly as a percentage, with
  the unclassified remainder shown rather than silently folded into "other".
- **No internal Lloyds data.** Everything here is inferred from public sources. If Lloyds ever
  supplied even a bare list of client company numbers, the three areas would become a clean
  three-way partition and the attrition label would stop being a proxy. The join seam is designed so
  that could drop in later without rework.

## 5. A naming correction we owe the client

The fourth target in `src/models/targets.py` is currently called **`attrition`**, and it means
"status becomes Proposal to Strike off". That is a company winding itself up, not a client moving to
Barclays. A struck-off company is not a relationship to win back, it is a dead company.

Left alone, the deliverable would use the client's own word for something they did not ask about.
The label is being renamed to **Voluntary Exit** and the word attrition reserved for provider
switching. The rename is deferred until the in-flight step 5 and 6 work lands, because it touches
`targets.py`, `data/processed/labels/` and `data/processed/model_matrix/`.

Related and worth knowing when reading the older notes: `reports/steps-5-6-modelling-guide.md` quotes
the strike-off rate as 3.4 to 3.8% while `targets.py` measures 6.7 to 8.5%. Both are right. The guide
measured the *state* at `t+H`, the code labels the *event* occurring anywhere in `t+1..t+H`. The code
explains this at `targets.py:26`; the guide is simply stale on this point.

## 6. Where each requirement is served in the repo

| Requirement | Artefact |
|---|---|
| Need signals over time | `data/processed/panel/`, `panel_deltas/` (49.6M rows, 25 delta features) |
| Procurement momentum | `data/processed/contracts_asof/`, `contracts_asof_ext/` |
| Labels | `src/models/targets.py`, `data/processed/labels/` |
| Models and SHAP | step 6, in flight |
| Lender identity and switching | `src/features/charges.py` (harvest running), then `lenders.py`, `data/processed/lender_panel/` |
| This traceability | `reports/client-requirements.md` |
