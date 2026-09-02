from typing import Optional

def match_within_ppm(
    observed_mz: float, expected_mz: float, ppm_tolerance: float
) -> Optional[float]:
    """
    Return the ppm error if observed_mz is within tolerance of expected_mz,
    else None
    """
    ppm_error = (observed_mz - expected_mz) / expected_mz * 1e6
    if abs(ppm_error) <= ppm_tolerance:
        return ppm_error
    return None

def find_best_match(
    expected_mz: float, observed_mzs: list[float], ppm_tolerance: float
) -> Optional[tuple[float, float]]:
    """
    Find the observed m/z closest to expected_mz within tolerance.

    Returns (matched_mz, ppm_error) or None if nothing in observed_mzs
    is within tolerance.
    """
    best: Optional[tuple[float, float]] = None
    for observed in observed_mzs:
        ppm_error = match_within_ppm(observed, expected_mz, ppm_tolerance)
        if ppm_error is None:
            continue
        if best is None or abs(ppm_error) < abs(best[1]):
            best = (observed, ppm_error)
    return best