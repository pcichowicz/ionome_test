from statistics import median
import pandas as pd

def align_features(
    per_sample_features: dict[str, list[dict]],
    mz_tolerance_ppm: float,
    rt_tolerance_sec: float,
) -> pd.DataFrame:
    """
    Pools every sample's features, sorts by m/z, and groups features into
    consensus rows when they fall within mz_tolerance_ppm AND rt_tolerance_sec
    of a group's running centroid.

    Returns a DataFrame: one row per consensus feature, columns
    ['feature_id', 'mz', 'rt'] plus one intensity column per sample_id
    (NaN where that sample had no matching feature).
    """
    pooled = []
    for sample_id, features in per_sample_features.items():
        for f in features:
            pooled.append({"sample_id": sample_id, "mz": f["mz"], "rt": f["rt"], "intensity": f["intensity"]})

    pooled.sort(key=lambda f: f["mz"])

    groups: list[dict] = []  # each: {"members": [...], "mz_values": [...], "rt_values": [...]}

    for feat in pooled:
        placed = False
        for group in groups:
            group_mz = median(group["mz_values"])
            group_rt = median(group["rt_values"])
            mz_ppm_error = abs(feat["mz"] - group_mz) / group_mz * 1e6
            rt_diff = abs(feat["rt"] - group_rt)

            candidate_mz_values = group["mz_values"] + [feat["mz"]]
            span_ppm = (max(candidate_mz_values) - min(candidate_mz_values)) / group_mz * 1e6

            candidate_rt_values = group["rt_values"] + [feat["rt"]]
            span_rt_sec = max(candidate_rt_values) - min(candidate_rt_values)

            if (mz_ppm_error <= mz_tolerance_ppm
                    and rt_diff <= rt_tolerance_sec
                    and span_ppm <= mz_tolerance_ppm
                    and span_rt_sec <= rt_tolerance_sec):
                group["members"].append(feat)
                group["mz_values"].append(feat["mz"])
                group["rt_values"].append(feat["rt"])
                placed = True
                break
        if not placed:
            groups.append({"members": [feat], "mz_values": [feat["mz"]], "rt_values": [feat["rt"]]})

    rows = []
    all_sample_ids = list(per_sample_features.keys())
    for i, group in enumerate(groups):
        row = {
            "feature_id": f"F{i+1:05d}",
            "mz": median(group["mz_values"]),
            "rt": median(group["rt_values"]),
        }
        for sample_id in all_sample_ids:
            matches = [m["intensity"] for m in group["members"] if m["sample_id"] == sample_id]
            row[sample_id] = matches[0] if matches else None  # first match if duplicate hits in same sample
        rows.append(row)

    return pd.DataFrame(rows)