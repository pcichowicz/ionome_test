"""
Adduct m/z <-> neutral mass conversions for negative-mode LC-MS.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
from itertools import combinations

from analysis.utils.constants import NON_SAMPLE_COLS

ELECTRON_MASS = 0.000549
PROTON_MASS = 1.007276
CHLORINE_MASS = 34.968853
SODIUM_MASS = 22.989770
HYDROGEN_MASS = 1.007825
FORMIC_ACID_MASS = 46.005480

# Mass shift applied to the neutral monoisotopic mass M to get the adduct m/z.
ADDUCT_MASS_SHIFTS: dict[str, float] = {
    "[M-H]-": - PROTON_MASS,
    "[M+Cl]-": CHLORINE_MASS + ELECTRON_MASS,
    "[M+FA-H]-": FORMIC_ACID_MASS - PROTON_MASS,
    "[M+Na-2H]-": SODIUM_MASS - 2 * HYDROGEN_MASS + ELECTRON_MASS,
}

def compute_adduct_mz(neutral_mass: float, adduct: str) -> float:
    """Given a compound's neutral monoisotopic mass, compute the expected
    m/z for a given adduct."""
    if adduct == "[2M-H]-":
        return 2 * neutral_mass - PROTON_MASS
    if adduct not in ADDUCT_MASS_SHIFTS:
        raise ValueError(f"Unknown adduct: {adduct!r}")
    return neutral_mass + ADDUCT_MASS_SHIFTS[adduct]


def compute_neutral_mass(observed_mz: float, adduct: str) -> float:
    """Inverse of compute_adduct_mz: given an observed m/z assumed to be a
    specific adduct, back-calculate the neutral monoisotopic mass."""
    if adduct == "[2M-H]-":
        return (observed_mz + PROTON_MASS) / 2
    if adduct not in ADDUCT_MASS_SHIFTS:
        raise ValueError(f"Unknown adduct: {adduct!r}")
    return observed_mz - ADDUCT_MASS_SHIFTS[adduct]

def known_adducts() -> list[str]:
    return list(ADDUCT_MASS_SHIFTS.keys()) + ["[2M-H]-"]

@dataclass
class AdductDef:
    name: str
    mass_shift: float
    multiplier: int = 1   # neutral_mass = (mz - mass_shift) / multiplier

NEGATIVE_ADDUCTS = [
    AdductDef("[M-H]-",       -1.007276),
    AdductDef("[M+Cl]-",      34.968853),
    AdductDef("[M+FA-H]-",    44.998201),
    AdductDef("[M-H2O-H]-",  -19.017841),
    AdductDef("[2M-H]-",      -1.007276, multiplier=2)
]

ISOTOPE_SPACING = 1.003355   # per extra 13C, same charge state
MAX_ISOTOPE_ORDER = 2        # check M+1, M+2 only

def annotate_adducts(
    aligned_features: pd.DataFrame,
    mz_tolerance_ppm: float = 10.0,
    rt_tolerance_sec: float = 3.0,
    correlation_threshold: float = 0.75,
    adduct_table: list[AdductDef] = NEGATIVE_ADDUCTS,
) -> pd.DataFrame:
    sample_cols = [c for c in aligned_features.columns if c not in NON_SAMPLE_COLS]
    features = aligned_features.to_dict("records")

    edges = []
    role_votes = {fid: {} for fid in aligned_features["feature_id"]}
    for a, b in combinations(features, 2):
        if abs(a["rt"] - b["rt"]) > rt_tolerance_sec:
            continue
        delta = b["mz"] - a["mz"]
        match = _match_delta(delta, a["mz"], adduct_table, mz_tolerance_ppm, mz_a=a["mz"], mz_b=b["mz"])
        if match is None:
            continue
        corr = _sample_correlation(a, b, sample_cols)
        if corr is None or corr < correlation_threshold:
            continue
        role_a, role_b = match
        edges.append((a["feature_id"], b["feature_id"], match))
        if role_a is not None:
            role_votes[a["feature_id"]][role_a] = role_votes[a["feature_id"]].get(role_a, 0) + 1
        if role_b is not None:
            role_votes[b["feature_id"]][role_b] = role_votes[b["feature_id"]].get(role_b, 0) + 1

    group_ids = _connected_components(aligned_features["feature_id"].tolist(), edges)

    result = aligned_features.copy()
    result["adduct_group_id"] = result["feature_id"].map(group_ids)
    result["ion_type"] = None
    result["neutral_mass"] = None
    for group_id, group_df in result.groupby("adduct_group_id"):
        _assign_ion_types(result, group_df, adduct_table, role_votes)  # <- role_votes now passed

    return result

def _match_delta(delta_mz, ref_mz, adduct_table, mz_tolerance_ppm, mz_a=None, mz_b=None):
    """
    Return (role_a, role_b) if delta_mz matches a known relationship.
    mz_a/mz_b (the raw m/z of each feature) are needed for dimer detection,
    which isn't a simple pairwise delta -- it's a ratio check.
    """
    tol = ref_mz * mz_tolerance_ppm / 1e6

    for n in range(1, MAX_ISOTOPE_ORDER + 1):
        if abs(delta_mz - n * ISOTOPE_SPACING) <= tol:
            return (None, f"isotope+{n}")

    # Monomer-to-monomer adducts (multiplier=1 only)
    monomers = [a for a in adduct_table if a.multiplier == 1]
    for x in monomers:
        for y in monomers:
            if x.name == y.name:
                continue
            if abs(delta_mz - (y.mass_shift - x.mass_shift)) <= tol:
                return (x.name, y.name)

    # Monomer-to-dimer: does mz_b look like 2x mz_a's neutral mass, shifted?
    if mz_a is not None and mz_b is not None:
        for mono in monomers:
            neutral_from_a = (mz_a - mono.mass_shift) / mono.multiplier
            for dimer in [a for a in adduct_table if a.multiplier == 2]:
                predicted_dimer_mz = 2 * neutral_from_a + dimer.mass_shift
                if abs(mz_b - predicted_dimer_mz) <= tol:
                    return (mono.name, dimer.name)

    return None

def _connected_components(feature_ids: list[str], edges: list[tuple]) -> dict[str, int]:
    """
    Union-find over feature_ids using edges (a, b, label) tuples.
    Returns {feature_id: group_id}, where group_id is an arbitrary but
    stable int — every feature gets one, including singletons with no edges.
    """
    parent = {fid: fid for fid in feature_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b, _label in edges:
        union(a, b)

    # Map each root to a stable, compact integer id
    roots = {}
    group_ids = {}
    next_id = 0
    for fid in feature_ids:
        root = find(fid)
        if root not in roots:
            roots[root] = next_id
            next_id += 1
        group_ids[fid] = roots[root]

    return group_ids

def _sample_correlation(a: dict, b: dict, sample_cols: list[str]) -> float | None:
    """
    Pearson correlation of two features' intensity vectors across samples.
    Checks overlapping NON-NULL sample count, not raw vector length --
    sparse aligned features (common in real cohort data, where many
    consensus features are only present in a subset of samples)
    otherwise degrade into unstable/degenerate correlations on 2-3 point
    fits.
    """
    vec_a = pd.Series([a[c] for c in sample_cols], dtype=float)
    vec_b = pd.Series([b[c] for c in sample_cols], dtype=float)

    valid_mask = vec_a.notna() & vec_b.notna()
    if valid_mask.sum() < 6:  # matches the min_valid=6 validated earlier
        return None

    vec_a_valid, vec_b_valid = vec_a[valid_mask], vec_b[valid_mask]
    if vec_a_valid.std() == 0 or vec_b_valid.std() == 0:
        return None

    return vec_a_valid.corr(vec_b_valid)

def _assign_ion_types(result, group_df, adduct_table, role_votes):
    if len(group_df) == 1:
        fid = group_df.iloc[0]["feature_id"]
        mz = group_df.iloc[0]["mz"]
        default = next(a for a in adduct_table if a.name == "[M-H]-")
        result.loc[result["feature_id"] == fid, "ion_type"] = "[M-H]- (assumed, ungrouped)"
        result.loc[result["feature_id"] == fid, "neutral_mass"] = mz - default.mass_shift
        return

    sample_cols = [c for c in result.columns
                   if c not in ("feature_id", "mz", "rt", "adduct_group_id", "ion_type", "neutral_mass")]

    # monomer_names = {a.name for a in adduct_table if a.multiplier == 1}

    # Priority 1: any group member whose edges identify it as [M-H]-?
    mh_candidates = [
        row["feature_id"] for _, row in group_df.iterrows()
        if role_votes.get(row["feature_id"], {}).get("[M-H]-", 0) > 0
    ]
    if mh_candidates:
        intensity = group_df.set_index("feature_id")[sample_cols].mean(axis=1)
        primary_fid = max(mh_candidates, key=lambda fid: intensity.loc[fid])
    else:
        dimer_names = {a.name for a in adduct_table if a.multiplier > 1}

        def is_dimer_only(fid):
            votes = role_votes.get(fid, {})
            return bool(votes) and set(votes.keys()) <= dimer_names

        eligible = group_df[~group_df["feature_id"].apply(is_dimer_only)]
        pool = eligible if len(eligible) > 0 else group_df
        mean_intensity = pool.set_index("feature_id")[sample_cols].mean(axis=1)
        primary_fid = mean_intensity.idxmax()

    primary_row = group_df.set_index("feature_id").loc[primary_fid]
    primary_adduct = next((a for a in adduct_table if a.name == "[M-H]-"), adduct_table[0])
    neutral_mass = (primary_row["mz"] - primary_adduct.mass_shift) / primary_adduct.multiplier

    for _, row in group_df.iterrows():
        fid = row["feature_id"]
        label = "[M-H]- (primary)" if fid == primary_fid else "grouped (unlabeled)"
        result.loc[result["feature_id"] == fid, "ion_type"] = label
        result.loc[result["feature_id"] == fid, "neutral_mass"] = neutral_mass