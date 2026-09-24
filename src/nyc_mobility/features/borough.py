"""Borough context with complete cross-zone coverage and strictly earlier observations."""

import numpy as np
import pandas as pd

from nyc_mobility.data.prepare import BOROUGHS
from nyc_mobility.evaluation.splits import require_complete_window
from nyc_mobility.features.temporal import effective_lags, make_features

STATIC_FEATURES = [f"borough_{name.lower().replace(' ', '_')}" for name in sorted(BOROUGHS)]
CONTEXT_FEATURES = ["borough_other_mean_lag_1", "borough_other_mean_lag_24"]


def make_borough_features(
    frame: pd.DataFrame,
    zones: pd.DataFrame,
    *,
    lookup_available_at: str,
    observation_delay_hours: int = 0,
) -> pd.DataFrame:
    """Exclude the focal zone; shift aggregated peer counts before joining target rows."""
    if (
        zones.empty
        or zones.zone_id.isna().any()
        or zones.zone_id.duplicated().any()
        or not zones.zone_id.between(2, 263).all()
        or (zones.zone_id % 1 != 0).any()
        or not zones.borough.isin(BOROUGHS).all()
    ):
        raise ValueError("Require unique NYC zone IDs and authoritative borough labels")
    available = pd.Timestamp(lookup_available_at)
    if available.tzinfo is None:
        raise ValueError("Lookup availability must include an explicit timezone")
    lags = effective_lags(observation_delay_hours)
    result = make_features(frame, observation_delay_hours=observation_delay_hours)
    if result.empty or result.hour.min() < available:
        raise ValueError("Lookup was unavailable for part of the requested feature history")
    ids = sorted(zones.zone_id.tolist())
    require_complete_window(
        result, ids, result.hour.min(), result.hour.max() + pd.Timedelta(hours=1)
    )
    labels = zones.set_index("zone_id").borough
    mapped = result.zone_id.map(labels)
    if "borough" in result and not result.borough.eq(mapped).all():
        raise ValueError("Panel borough metadata disagrees with the authoritative lookup")
    if "borough" not in result:
        result["borough"] = mapped
    for name, column in zip(sorted(BOROUGHS), STATIC_FEATURES, strict=True):
        result[column] = mapped.eq(name).astype("int8")
    # Complete rectangular coverage is checked above; no absent peer can become a zero.
    demand = result.pivot(index="hour", columns="zone_id", values="demand").reindex(columns=ids)
    peers = pd.DataFrame(index=demand.index, columns=ids, dtype=float)
    for borough in sorted(BOROUGHS):
        members = labels.loc[labels == borough].index.tolist()
        if not members:
            continue
        if len(members) == 1:
            peers[members[0]] = 0.0  # Explicit empty-peer mean; count is exposed below.
        else:
            values = demand[members].to_numpy(dtype=float)
            peers[members] = (values.sum(axis=1, keepdims=True) - values) / (len(members) - 1)
    result["borough_other_count"] = mapped.map(zones.groupby("borough").size() - 1).astype(int)
    time_index = demand.index.get_indexer(result.hour)
    zone_index = pd.Index(ids).get_indexer(result.zone_id)
    for lag in [1, 24]:
        values = peers.shift(lags[f"lag_{lag}"]).to_numpy()
        result[f"borough_other_mean_lag_{lag}"] = values[time_index, zone_index]
    if not np.isfinite(result[STATIC_FEATURES]).all().all():
        raise ValueError("Invalid static borough features")
    return result
