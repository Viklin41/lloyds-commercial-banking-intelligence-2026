# Gazette Feature Catalogue (company-level variables)

A ground-up library of individual, explainable variables derived from the NB10 Gazette
notice dataset (`data/processed/nb10_gazette_notices.csv`). The goal is a robust set of
interpretable company-level features to merge into the master company dataset for later
analysis. This is **not** a risk score or a predictive model, every variable is a single,
explainable signal.

## Source and grain

- **Raw columns available:** `company_name`, `CompanyNumber`, `notice_code`, `notice_type`,
  `notice_date`, `postcode`, `notice_url`.
- **Rows:** 284,230 notices, dated 2023-06-30 to 2026-06-30 (a 3-year window).
- **Grain of the output:** one row per company. Aggregate all notices for a company into
  a single feature row.
- **Merge key:** `CompanyNumber` only (never company name). Name is used for optional
  lower-confidence matching, flagged separately.
- **Reproducibility:** every recency and count-window variable is computed against a pinned
  `SNAPSHOT_DATE` constant (use the crawl end, 2026-06-30, or an explicit pinned date), not
  `today()`, so re-runs are stable.

## Important honesty flags (read before using)

1. **This crawl is the corporate-insolvency category.** It captures insolvency and distress
   stages in depth, but it does **not** contain company formation, compulsory strike-off,
   dissolution, or restoration notices. Variables in the "Company lifecycle" category that
   depend on those are marked **[needs additional crawl]** and are not derivable from the
   current file.
2. **Filter ceremonial noise first.** Roughly 10k rows are honours and state notices (Order
   of the British Empire, Royal Victorian Order, Proclamations, etc.). Drop any notice whose
   type is not in the insolvency family before building features.
3. **Postcode is unreliable as company location.** The Gazette postcode is frequently the
   insolvency practitioner's or court's address, not the company's trading address. Treat
   geographic variables as verification aids, not location analytics.
4. **Only 55% of notices carry a CompanyNumber.** Matching and data-quality variables are
   first-class, not optional.
5. **Absence is a valid signal.** A company with no Gazette notice is the normal, healthy
   case, not a missing value. `gaz_has_any_notice = 0` is meaningful.

---

## Notice-family definitions (used by many variables below)

Group the raw `notice_type` values into families once, then reuse everywhere:

| Family | notice_type values included |
|---|---|
| `petition` | Petitions to Wind Up (Companies); Service of Petition |
| `winding_up_order` | Winding-Up Orders |
| `voluntary_liquidation` | Resolutions for Winding-up; Resolutions for Winding Up; Appointment of Liquidators |
| `administration` | Appointment of Administrators; Administration Orders; Appointment of Administrative Receivers |
| `moratorium` | Moratoria, Prohibited Names and Other (moratorium portion) |
| `creditor_process` | Meetings of Creditors; Notices to Creditors; Qualifying Decision Procedure; Deemed Consent; Notices to Members |
| `dividend` | Notice of Intended Dividends; Notice of Dividends |
| `closing` | Final Meetings; Annual Liquidation Meetings |
| `petition_dismissed` | Dismissal of Winding Up Petition |
| `prohibited_name_reuse` | Moratoria, Prohibited Names and Other: Re-use of a Prohibited Name |
| `cross_border` | Court Petitions and Orders: Cross-border Insolvencies |
| `other_insolvency` | Other Corporate Insolvency Notices |
| `noise` (exclude) | all honours / ceremonial / Crown types |

---

## Category 1: Insolvency and financial distress indicators

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_total_insolvency_notice_count` | Integer | Total insolvency-family notices for the company | Count all non-noise notices per `CompanyNumber` | Overall volume of distress activity | High |
| `gaz_liquidation_notice_count` | Integer | Liquidation activity | Count of `voluntary_liquidation` + `winding_up_order` | Core signal that the company is being wound up | High |
| `gaz_winding_up_petition_count` | Integer | Court petitions to wind up | Count of `petition` | A creditor is asking the court to close the company | High |
| `gaz_winding_up_order_count` | Integer | Compulsory closure orders | Count of `winding_up_order` | Court has ordered closure, most severe stage | High |
| `gaz_administration_count` | Integer | Administration events | Count of `administration` | Formal rescue or controlled wind-down | High |
| `gaz_moratorium_count` | Integer | Pre-insolvency moratoria | Count of `moratorium` | Early "breathing space" warning before formal insolvency | Medium |
| `gaz_creditors_process_count` | Integer | Creditor decision activity | Count of `creditor_process` | Creditors are being convened, active case | Medium |
| `gaz_dividend_notice_count` | Integer | Distributions to creditors | Count of `dividend` | Late-stage, assets being paid out | Medium |

## Category 2: Legal and operational events

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_prohibited_name_reuse_flag` | Boolean | Phoenix-company behaviour | 1 if any `prohibited_name_reuse` notice | Director restarting a failed business under a new entity, fraud/phoenix risk | High |
| `gaz_petition_dismissed_flag` | Boolean | Survival / recovery | 1 if any `petition_dismissed` | Company fought off a winding-up petition, a rare positive signal | High |
| `gaz_cross_border_insolvency_flag` | Boolean | International insolvency | 1 if any `cross_border` | Company has cross-jurisdiction exposure | Medium |
| `gaz_receiver_appointed_flag` | Boolean | Secured lender enforcing | 1 if `Appointment of Administrative Receivers` present | A secured creditor has seized control | Medium |
| `gaz_other_insolvency_flag` | Boolean | Uncategorised insolvency event | 1 if any `other_insolvency` | Catch-all so nothing is silently dropped | Low |

## Category 3: Company lifecycle events

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_reached_closing_stage_flag` | Boolean | Near end of wind-up | 1 if any `closing` notice | Liquidation is finishing, company close to dissolution | Medium |
| `gaz_dissolution_proxy_flag` | Boolean | Likely dissolved soon after | 1 if latest notice is `closing` and older than N months | Proxy for dissolution (true dissolution notice not in this crawl) | Medium |
| `gaz_formation_flag` | Boolean | Company formation | **[needs additional crawl]** not in insolvency feed | Lifecycle start | Low |
| `gaz_strike_off_first_flag` | Boolean | First strike-off notice | **[needs additional crawl]** "Companies" strike-off category | Compulsory strike-off begun | High |
| `gaz_strike_off_final_flag` | Boolean | Final strike-off / dissolution | **[needs additional crawl]** | Company removed from register | High |
| `gaz_restoration_flag` | Boolean | Restored to register | **[needs additional crawl]** | Company brought back, unusual event | Medium |

## Category 4: Notice frequency and recurrence

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_notice_count_total` | Integer | All notices (incl. noise-filtered) | Count rows per company | Base volume feature | High |
| `gaz_distinct_notice_type_count` | Integer | Breadth of event types | `nunique(notice_type)` per company | Many different event types = a complex, active case | Medium |
| `gaz_notice_count_12m` | Integer | Notices in trailing 12 months | Count where `notice_date >= SNAPSHOT_DATE - 365d` | Recent intensity of distress | High |
| `gaz_notice_count_24m` | Integer | Notices in trailing 24 months | Count where `notice_date >= SNAPSHOT_DATE - 730d` | Medium-term intensity | Medium |
| `gaz_notice_burst_flag` | Boolean | Rapid escalation | 1 if >=3 notices within any 90-day window | Fast-moving cases collapse quickly | Medium |
| `gaz_recurring_distress_flag` | Boolean | Repeat distress episodes | 1 if notices fall on >=2 distinct dates > 180 days apart | Chronic vs one-off distress | Medium |

## Category 5: Timeline and recency measures

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_first_notice_date` | Date | When distress first appeared | `min(notice_date)` | Anchor for how long the company has been in trouble | Medium |
| `gaz_latest_notice_date` | Date | Most recent event | `max(notice_date)` | Freshness of the signal | High |
| `gaz_days_since_latest_notice` | Integer | Recency | `SNAPSHOT_DATE - latest_notice_date` in days | Recent distress is far more actionable than old | High |
| `gaz_notice_span_days` | Integer | Duration in the record | `latest - first` in days | Long span = drawn-out case; short = sudden | Medium |
| `gaz_recent_notice_90d_flag` | Boolean | Very recent activity | 1 if `days_since_latest_notice <= 90` | Live, current distress | High |
| `gaz_recent_notice_365d_flag` | Boolean | Activity in last year | 1 if `days_since_latest_notice <= 365` | Signal is still current | High |
| `gaz_active_case_flag` | Boolean | Case likely still open | 1 if latest notice is an open stage (petition/administration/liquidation appointment) and within 365d | Distinguishes ongoing from concluded cases | High |

## Category 6: Event progression and stage of distress

A single ordinal ladder captures how far a company has moved through the insolvency process.
Stage mapping (higher = further into distress):

```
1  early        moratorium
2  petition     petition, service of petition
3  formal        winding_up_order, administration, voluntary_liquidation (order/appointment made)
4  creditor      creditor_process (meetings/decisions under way)
5  distribution  dividend (assets being paid out)
6  closing       closing (final meetings, winding down complete)
```

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_max_distress_stage` | Integer (1-6) | Furthest stage reached | Max stage over all the company's notices | Single ordinal severity of position reached | High |
| `gaz_current_stage` | Categorical | Stage of the latest notice | Stage of the notice with `max(notice_date)` | Where the company is now, not just its worst point | High |
| `gaz_stage_progressed_flag` | Boolean | Escalation over time | 1 if stage increased by >=2 from earliest to latest notice | Distinguishes deteriorating cases | High |
| `gaz_petition_to_liquidation_flag` | Boolean | Petition matured into closure | 1 if has a `petition` and a later `winding_up_order`/`voluntary_liquidation` | Confirms the petition led to actual closure | High |
| `gaz_administration_to_liquidation_flag` | Boolean | Rescue failed | 1 if `administration` followed by a later liquidation notice | Attempted rescue collapsed into wind-up | Medium |
| `gaz_days_petition_to_order` | Integer | Speed of collapse | Days from first `petition` to first `winding_up_order`/liquidation | Fast collapse = weaker company or aggressive creditor | Medium |

## Category 7: Severity indicators

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_compulsory_liquidation_flag` | Boolean | Court-ordered closure | 1 if any `winding_up_order` | Compulsory route, more severe than voluntary | High |
| `gaz_voluntary_liquidation_flag` | Boolean | Members/creditors voluntary | 1 if `voluntary_liquidation` present and no `winding_up_order` | Voluntary wind-up, less severe than compulsory | Medium |
| `gaz_court_involved_flag` | Boolean | Court process present | 1 if any `petition` or `winding_up_order` | Distinguishes court-driven from voluntary cases | High |
| `gaz_severity_tier` | Categorical | Descriptive severity label | Map `max_distress_stage` to {none, early_warning, formal_insolvency, terminal} | A single interpretable label from notice types alone (single-source, not a composite score) | Medium |

Note: `gaz_severity_tier` is a descriptive categorical label derived only from Gazette notice
types. It is not a composite or predictive risk score and blends in no external data.

## Category 8: Binary event flags (clean 0/1 for downstream models)

A tidy mirror of the families as plain flags, easy to feed straight into any model.

| Variable | Type | Calculation | Imp |
|---|---|---|---|
| `gaz_has_any_notice` | Boolean | 1 if company appears at all (else 0) | High |
| `gaz_has_winding_up_petition` | Boolean | 1 if any `petition` | High |
| `gaz_has_winding_up_order` | Boolean | 1 if any `winding_up_order` | High |
| `gaz_has_liquidation` | Boolean | 1 if any `voluntary_liquidation` or `winding_up_order` | High |
| `gaz_has_administration` | Boolean | 1 if any `administration` | High |
| `gaz_has_moratorium` | Boolean | 1 if any `moratorium` | Medium |
| `gaz_has_creditors_process` | Boolean | 1 if any `creditor_process` | Medium |
| `gaz_has_dividend_notice` | Boolean | 1 if any `dividend` | Medium |
| `gaz_has_closing_notice` | Boolean | 1 if any `closing` | Medium |
| `gaz_has_prohibited_name_reuse` | Boolean | 1 if any `prohibited_name_reuse` | High |
| `gaz_has_petition_dismissed` | Boolean | 1 if any `petition_dismissed` | High |
| `gaz_has_cross_border_insolvency` | Boolean | 1 if any `cross_border` | Medium |

## Category 9: Geographic variables

Use with the caveat that Gazette postcode is often the practitioner or court, not the company.

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_notice_postcode` | Categorical | Postcode on the latest notice | Postcode of `max(notice_date)` notice | Raw geographic tag | Low |
| `gaz_notice_postcode_area` | Categorical | Outward area (e.g. GL, DN) | Leading letters of postcode | Coarse region grouping, less noisy than full postcode | Medium |
| `gaz_postcode_matches_ch_flag` | Boolean | Agreement with Companies House | 1 if notice postcode area matches CH registered postcode area | Confirms the match is the right company (disambiguation) | High |
| `gaz_region` | Categorical | Region from postcode area | Map postcode area to UK region | Optional geographic segmentation | Low |

## Category 10: Data quality and matching variables

| Variable | Type | What it measures | How to calculate | Why useful | Imp |
|---|---|---|---|---|---|
| `gaz_has_company_number` | Boolean | Notice carried a company number | 1 if `CompanyNumber` present on any notice for this match | Trust level of the match | High |
| `gaz_match_method` | Categorical | How the company was matched | {number, name_and_postcode, name_only, unmatched} | Governs confidence and lets low-confidence rows be filtered | High |
| `gaz_name_only_match_flag` | Boolean | Matched without a number | 1 if matched by name only | Flags weaker matches for review | Medium |
| `gaz_postcode_present_flag` | Boolean | Postcode available | 1 if any notice had a postcode | Enables the geographic and disambiguation checks | Low |
| `gaz_source_notice_urls` | String (list) | Provenance | Concatenate `notice_url` values | Audit trail back to the original notices | Medium |

---

## Logical progression summary (transitions worth capturing)

The insolvency notices form a natural sequence. The progression variables above encode it:

```
moratorium  ->  petition  ->  winding-up order OR administration OR voluntary liquidation
                                     ->  creditors' meetings  ->  dividends  ->  final meeting
petition  ->  DISMISSED   (survival branch, positive signal)
administration  ->  later liquidation   (rescue failed)
any insolvency  ->  prohibited-name re-use   (phoenix restart of a new company)
```

The most informative transition features are:
- `gaz_petition_to_liquidation_flag` (a threat became reality),
- `gaz_administration_to_liquidation_flag` (a rescue failed),
- `gaz_stage_progressed_flag` (the case is deteriorating),
- `gaz_petition_dismissed_flag` (the company survived).

## Suggested build order for a future notebook section

1. Filter out ceremonial noise, map `notice_type` to the families above.
2. Build the per-notice stage number.
3. Group by `CompanyNumber`, compute the counts, flags, dates, and stage aggregates.
4. Compute recency against a pinned `SNAPSHOT_DATE`.
5. Add matching and data-quality variables.
6. Left-join the resulting one-row-per-company table onto the master dataset on `CompanyNumber`,
   filling non-matched companies with `gaz_has_any_notice = 0` and counts = 0 (not null).
