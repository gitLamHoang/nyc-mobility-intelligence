"""Append the frozen citywide weather bundle to the original histogram pipeline."""

from nyc_mobility.features.temporal import FEATURES, NUMERIC_FEATURES
from nyc_mobility.features.weather_bundle import WEATHER_BUNDLE_FEATURES
from nyc_mobility.models.train import estimators

DELAYS = {"weather_3h": 3, "weather_6h": 6}
BUNDLES = {name: [*FEATURES, *WEATHER_BUNDLE_FEATURES] for name in DELAYS}


def weather_estimator(config: dict, bundle: str):
    """Construct fresh preprocessing and estimator, retaining numeric weather NaNs."""
    if bundle not in BUNDLES:
        raise ValueError("Unknown frozen weather feature bundle")
    model = estimators(config)["hist_gradient_boosting"]
    model[0].set_params(
        transformers=[
            model[0].transformers[0],
            ("numeric", "passthrough", [*NUMERIC_FEATURES, *WEATHER_BUNDLE_FEATURES]),
        ]
    )
    return model
