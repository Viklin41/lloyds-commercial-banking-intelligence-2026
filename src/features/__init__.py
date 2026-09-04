"""Feature engineering for the Companies House SHAP feature matrix.

Three concerns, one per module:
- ``ch_static``  : vectorized features computable for ALL companies from the base CSV.
- ``ch_api``     : per-company enrichment from the live Companies House APIs (needs a key).
- ``sample``     : select the prioritized subset of companies to send to the live APIs.
- ``panel``      : build the company-month panel from the historical bulk snapshots.

Formulas are lifted verbatim from the sneha enrichment notebooks
(04_exiting_relationships, 06_director_changes) so the matrix matches them exactly.
"""

from . import ch_static, ch_api, sample, panel  # noqa: F401
