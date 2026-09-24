"""Append only the frozen borough predictors to the existing histogram pipeline."""

from nyc_mobility.features.borough import CONTEXT_FEATURES, STATIC_FEATURES
from nyc_mobility.features.temporal import FEATURES, NUMERIC_FEATURES
from nyc_mobility.models.train import estimators

BUNDLES = {
    "borough_static": [*FEATURES, *STATIC_FEATURES],
    "borough_context": [*FEATURES, *STATIC_FEATURES, *CONTEXT_FEATURES],
}


def borough_estimator(config: dict, bundle: str):
    if bundle not in BUNDLES:
        raise ValueError("Unknown frozen borough feature bundle")
    model = estimators(config)["hist_gradient_boosting"]
    additional = BUNDLES[bundle][len(FEATURES) :]
    model[0].set_params(
        transformers=[
            model[0].transformers[0],
            ("numeric", "passthrough", [*NUMERIC_FEATURES, *additional]),
        ]
    )
    return model
