"""Bounded research candidates; the serving-model factory is deliberately unchanged."""

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder
from xgboost import XGBRegressor

from nyc_mobility.features.temporal import NUMERIC_FEATURES


def dense_float32(values):
    """Preserve actual zero values instead of implicitly treating them as missing."""
    return np.asarray(values, dtype=np.float32)


def xgboost_estimator(parameters: dict, depth: int):
    encoding = ColumnTransformer(
        [
            (
                "zone",
                OneHotEncoder(sparse_output=False, handle_unknown="error", dtype=np.float32),
                ["zone_id"],
            ),
            ("numeric", "passthrough", NUMERIC_FEATURES),
        ],
        sparse_threshold=0,
    )
    return make_pipeline(
        encoding,
        FunctionTransformer(dense_float32),
        XGBRegressor(
            **parameters,
            max_depth=depth,
            missing=np.nan,
            early_stopping_rounds=None,
            validate_parameters=True,
        ),
    )
