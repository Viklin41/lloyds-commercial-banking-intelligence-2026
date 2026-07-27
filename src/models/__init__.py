"""Modelling: self-labelled targets over the company-month panel, and the models
trained on them.

- ``targets`` : forward-looking labels at quarterly origins, plus the sampled
  modelling matrix that joins them to the delta and contract features.
- ``train``   : the out-of-time split, LightGBM and a logistic floor per target,
  recalibration, precision@N on the unsampled population, SHAP, and scoring.
"""

from . import targets, train  # noqa: F401
