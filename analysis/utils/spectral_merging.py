from typing import Optional

def merge_ms2_spectra(
    spectra: list[list[tuple[float, float]]],
    fragment_mz_tolerance_da: float,
) -> list[tuple[float, float]]:
    """
    Merges multiple MS2 spectra (each a list of (mz, intensity) peaks)
    from different samples/triggering events into one consensus spectrum,
    fragments within tolerance of each
    other across contributing spectra are treated as the same fragment
    ion and their intensities combined, improving signal-to-noise over
    any single spectrum.

    Binning approach: pool every peak from every spectrum, sort by m/z,
    greedily group peaks within fragment_mz_tolerance_da of a running
    group centroid.
    Each output peak's intensity is the SUM of its group's member
    intensities (not an average)
    """
    all_peaks = [p for spectrum in spectra for p in spectrum]
    if not all_peaks:
        return []

    all_peaks.sort(key=lambda p: p[0])

    groups: list[dict] = []
    for mz, intensity in all_peaks:
        placed = False
        for group in groups:
            group_mz = sum(group["mzs"]) / len(group["mzs"])
            if abs(mz - group_mz) <= fragment_mz_tolerance_da:
                group["mzs"].append(mz)
                group["total_intensity"] += intensity
                placed = True
                break
        if not placed:
            groups.append({"mzs": [mz], "total_intensity": intensity})

    merged = [
        (sum(g["mzs"]) / len(g["mzs"]), g["total_intensity"])
        for g in groups
    ]
    merged.sort(key=lambda p: -p[1])  # most intense fragments first
    return merged

def find_feature_for_mz(
    features: list[dict], target_mz: float, ppm_tolerance: float
) -> Optional[dict]:
    """
    Find the detected feature closest to target_mz within tolerance
    """
    best: Optional[dict] = None
    best_ppm = None
    for feature in features:
        ppm_error = abs(feature["mz"] - target_mz) / target_mz * 1e6
        if ppm_error <= ppm_tolerance and (best_ppm is None or ppm_error < best_ppm):
            best = feature
            best_ppm = ppm_error
    return best