from pyteomics import mzml
import pandas as pd
from pathlib import Path
import numpy as np
from typing import Optional

from analysis.utils.feature_utils import group_into_features

class PyteomicsPrecursorReader:
    """
    Dual-format (mzML/mzXML) precursor m/z reader. Dispatches by file
    extension, since the two formats use different key structures for
    MS2 precursor information.
    """

    def get_precursor_mzs(self, raw_path: Path) -> list[float]:
        suffix = raw_path.suffix.lower()
        if suffix == ".mzml":
            return self._get_precursor_mzs_mzml(raw_path)
        elif suffix == ".mzxml":
            return self._get_precursor_mzs_mzxml(raw_path)
        else:
            raise ValueError(f"Unsupported raw file extension '{suffix}' for {raw_path}")

    def _get_precursor_mzs_mzml(self, mzml_path: Path) -> list[float]:
        from pyteomics import mzml

        precursor_mzs: list[float] = []
        with mzml.read(str(mzml_path)) as reader:
            for spectrum in reader:
                if spectrum.get("ms level") != 2:
                    continue
                for precursor in spectrum.get("precursorList", {}).get("precursor", []):
                    for ion in precursor.get("selectedIonList", {}).get("selectedIon", []):
                        mz = ion.get("selected ion m/z")
                        if mz is not None:
                            precursor_mzs.append(float(mz))
        return precursor_mzs

    def _get_precursor_mzs_mzxml(self, mzxml_path: Path) -> list[float]:
        from pyteomics import mzxml

        precursor_mzs: list[float] = []
        with mzxml.read(str(mzxml_path)) as reader:
            for spectrum in reader:
                if spectrum.get("msLevel") != 2:
                    continue
                for precursor_entry in spectrum.get("precursorMz", []):
                    mz = precursor_entry.get("precursorMz")
                    if mz is not None:
                        precursor_mzs.append(float(mz))
        return precursor_mzs

class PyteomicsFeatureDetector:
    """
    Feature detection via pyteomics + the custom feature_picking algorithm.
    Writes JSON (FEATURE_FILE_SUFFIX)
    """

    def detect_features(self, mzml_path: Path, output_path: Path, params: dict) -> list[dict]:
        import json

        scans = load_ms1_scans(mzml_path)
        peaks_width_sec = params.get("peak_width", [10, 60])
        min_peak_width_sec = peaks_width_sec[0]

        rts = [s["rt"] for s in scans]
        scan_interval_sec = float(np.median(np.diff(sorted(rts))))

        min_scans = max(2, int(round(min_peak_width_sec / scan_interval_sec)))

        features = group_into_features(
            scans,
            mz_ppm_tolerance=float(params.get("mass_error_ppm", 5.0)),
            min_scans=min_scans,
            noise_threshold=float(params.get("noise_threshold", 8000.0)),
            max_gaps=int(params.get("max_gaps", 2)),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(features, f, indent=2)
        return features

def load_ms1_scans(raw_path: Path) -> list[dict]:
    """
    Pull all MS1 scans out of an mzML or mzXML file as plain dicts of
    numpy arrays, via pyteomics. Dispatches by file extension; both
    branches use the same unit_info-based RT handling, since neither
    format's RT unit should be assumed.
    """
    suffix = raw_path.suffix.lower()
    if suffix == ".mzml":
        from pyteomics import mzml as reader_module
        ms_level_key, scan_time_getter = "ms level", _mzml_scan_time
    elif suffix == ".mzxml":
        from pyteomics import mzxml as reader_module
        ms_level_key, scan_time_getter = "msLevel", _mzxml_scan_time
    else:
        raise ValueError(f"Unsupported raw file extension '{suffix}' for {raw_path}")

    scans = []
    with reader_module.read(str(raw_path)) as reader:
        for spectrum in reader:
            if spectrum.get(ms_level_key) != 1:
                continue

            mz = np.asarray(spectrum.get("m/z array", []))
            intensity = np.asarray(spectrum.get("intensity array", []))
            if mz.size == 0:
                continue

            rt_sec = scan_time_getter(spectrum)
            scans.append({"rt": rt_sec, "mz": mz, "intensity": intensity})
    return scans

def _mzml_scan_time(spectrum: dict) -> float:
    scan_time = spectrum["scanList"]["scan"][0]["scan start time"]
    unit = getattr(scan_time, "unit_info", "minute")
    return float(scan_time) * 60.0 if unit == "minute" else float(scan_time)

def _mzxml_scan_time(spectrum: dict) -> float:
    scan_time = spectrum["retentionTime"]
    unit = getattr(scan_time, "unit_info", "minute")
    return float(scan_time) * 60.0 if unit == "minute" else float(scan_time)

def _spectrum_matches_precursor(spectrum: dict, target_mz: float, tolerance_da: float) -> bool:
    """
    True if any selected ion in this MS2 spectrum's precursor info falls
    within tolerance_da of target_mz.Handles both mzML's nested
    precursorList/selectedIonList structure and mzXML's flatter
    precursorMz list structure
    """
    if "precursorList" in spectrum:  # mzML shape
        for precursor in spectrum.get("precursorList", {}).get("precursor", []):
            for ion in precursor.get("selectedIonList", {}).get("selectedIon", []):
                mz = ion.get("selected ion m/z")
                if mz is not None and abs(float(mz) - target_mz) <= tolerance_da:
                    return True
        return False

    if "precursorMz" in spectrum:  # mzXML shape
        for precursor_entry in spectrum.get("precursorMz", []):
            mz = precursor_entry.get("precursorMz")
            if mz is not None and abs(float(mz) - target_mz) <= tolerance_da:
                return True
        return False

    return False

class PyteomicsSpectralPurityReader:
    """
    Precursor isolation purity: for each MS2 scan matching the
    target precursor, look at the preceding MS1 scan's peaks within the
    isolation window and compute what fraction belongs to the target ion.
    """

    TARGET_WINDOW_DA = 0.01

    def compute_precursor_purity(
            self, mzml_path: Path, precursor_mz: float, isolation_window_da: float
    ) -> Optional[float]:
        from pyteomics import mzml

        half_window = isolation_window_da / 2.0
        purities: list[float] = []
        last_ms1_peaks: Optional[np.ndarray] = None

        with mzml.read(str(mzml_path)) as reader:
            for spectrum in reader:
                ms_level = spectrum.get("ms level")

                if ms_level == 1:
                    mz_arr = np.asarray(spectrum.get("m/z array", []))
                    intensity_arr = np.asarray(spectrum.get("intensity array", []))
                    last_ms1_peaks = (
                        np.column_stack([mz_arr, intensity_arr]) if mz_arr.size else None
                    )
                    continue

                if ms_level != 2 or last_ms1_peaks is None:
                    continue

                if not _spectrum_matches_precursor(spectrum, precursor_mz, 0.01):
                    continue

                mz_array = last_ms1_peaks[:, 0]
                intensity_array = last_ms1_peaks[:, 1]

                window_mask = (mz_array >= precursor_mz - half_window) & (
                        mz_array <= precursor_mz + half_window
                )
                window_total = intensity_array[window_mask].sum()
                if window_total <= 0:
                    continue

                target_mask = (mz_array >= precursor_mz - self.TARGET_WINDOW_DA) & (
                        mz_array <= precursor_mz + self.TARGET_WINDOW_DA
                )
                target_total = intensity_array[target_mask].sum()
                purities.append(float(target_total / window_total))

        if not purities:
            return None
        return sum(purities) / len(purities)

class PyteomicsMS2SpectrumReader:
    def __init__(self, min_relative_intensity: float = 0.01):
        self.min_relative_intensity = min_relative_intensity

    def get_ms2_spectrum(
        self, raw_path: Path, precursor_mz: float, precursor_tolerance_da: float = 0.01
    ) -> list[tuple[float, float]]:
        suffix = raw_path.suffix.lower()
        if suffix == ".mzml":
            return self._get_ms2_spectrum_mzml(raw_path, precursor_mz, precursor_tolerance_da)
        elif suffix == ".mzxml":
            return self._get_ms2_spectrum_mzxml(raw_path, precursor_mz, precursor_tolerance_da)
        else:
            raise ValueError(f"Unsupported raw file extension '{suffix}' for {raw_path}")

    def _get_ms2_spectrum_mzml(self, mzml_path, precursor_mz, precursor_tolerance_da):
        from pyteomics import mzml
        best_peaks, best_tic = None, -1.0

        with mzml.read(str(mzml_path)) as reader:
            for spectrum in reader:
                if spectrum.get("ms level") != 2:
                    continue
                if not _spectrum_matches_precursor(spectrum, precursor_mz, precursor_tolerance_da):
                    continue
                mz_arr = np.asarray(spectrum.get("m/z array", []))
                intensity_arr = np.asarray(spectrum.get("intensity array", []))
                if mz_arr.size == 0:
                    continue
                peaks = np.column_stack([mz_arr, intensity_arr])
                tic = float(peaks[:, 1].sum())
                if tic > best_tic:
                    best_tic, best_peaks = tic, peaks

        return self._filter_peaks(best_peaks)

    def _get_ms2_spectrum_mzxml(self, mzxml_path, precursor_mz, precursor_tolerance_da):
        from pyteomics import mzxml
        best_peaks, best_tic = None, -1.0

        with mzxml.read(str(mzxml_path)) as reader:
            for spectrum in reader:
                if spectrum.get("msLevel") != 2:
                    continue
                if not _spectrum_matches_precursor(spectrum, precursor_mz, precursor_tolerance_da):
                    continue
                mz_arr = np.asarray(spectrum.get("m/z array", []))
                intensity_arr = np.asarray(spectrum.get("intensity array", []))
                if mz_arr.size == 0:
                    continue
                peaks = np.column_stack([mz_arr, intensity_arr])
                tic = float(peaks[:, 1].sum())
                if tic > best_tic:
                    best_tic, best_peaks = tic, peaks

        return self._filter_peaks(best_peaks)

    def _filter_peaks(self, best_peaks):
        if best_peaks is None:
            return []
        base_peak_intensity = float(best_peaks[:, 1].max())
        if base_peak_intensity <= 0:
            return []
        floor = base_peak_intensity * self.min_relative_intensity
        filtered = best_peaks[best_peaks[:, 1] >= floor]
        return [(float(mz), float(intensity)) for mz, intensity in filtered]

def compute_ms1_coelution_purity(
    ms1_scans: list[dict],
    target_mz: float,
    target_rt_sec: float,
    isolation_window_da: float,
    mz_ppm_tolerance: float = 10.0,
) -> float | None:
    """
    Computes precursor purity directly from MS1 co-elution data

    ms1_scans: output of load_ms1_scans() for one sample (list of
    {"rt": float_sec, "mz": ndarray, "intensity": ndarray}).

    Returns None if no MS1 scan exists near target_rt_sec (shouldn't
    normally happen if target_rt_sec came from a real detected feature
    in that sample) or if the target ion itself isn't found within the
    window.
    """
    if not ms1_scans:
        return None

    closest_scan = min(ms1_scans, key=lambda s: abs(s["rt"] - target_rt_sec))

    half_window = isolation_window_da / 2
    window_mask = (
        (closest_scan["mz"] >= target_mz - half_window)
        & (closest_scan["mz"] <= target_mz + half_window)
    )
    window_intensities = closest_scan["intensity"][window_mask]
    window_mzs = closest_scan["mz"][window_mask]

    if len(window_mzs) == 0:
        return None

    tol = target_mz * mz_ppm_tolerance / 1e6
    target_mask = abs(window_mzs - target_mz) <= tol
    target_intensity = window_intensities[target_mask].sum()

    total_window_intensity = window_intensities.sum()
    if total_window_intensity == 0:
        return None

    return float(target_intensity / total_window_intensity)

def _get_precursor_mz_mzml(spectrum: dict) -> float | None:
    for precursor in spectrum.get("precursorList", {}).get("precursor", []):
        for ion in precursor.get("selectedIonList", {}).get("selectedIon", []):
            mz = ion.get("selected ion m/z")
            if mz is not None:
                return float(mz)
    return None


def _get_precursor_mz_mzxml(spectrum: dict) -> float | None:
    for precursor_entry in spectrum.get("precursorMz", []):
        mz = precursor_entry.get("precursorMz")
        if mz is not None:
            return float(mz)
    return None


def build_ms2_index(raw_path: Path) -> list[tuple[float, float, list[tuple[float, float]]]]:
    """
    Parses a raw file ONCE, extracting every MS2 spectrum's precursor m/z,
    total ion current, and peak list. Returns a list of
    (precursor_mz, tic, peaks), sorted by precursor_mz. Call once per
    sample and reuse -- avoids re-parsing the same file per group lookup.
    """
    suffix = raw_path.suffix.lower()
    entries = []

    if suffix == ".mzml":
        from pyteomics import mzml
        with mzml.read(str(raw_path)) as reader:
            for spectrum in reader:
                if spectrum.get("ms level") != 2:
                    continue
                precursor_mz = _get_precursor_mz_mzml(spectrum)
                if precursor_mz is None:
                    continue
                mz_arr = np.asarray(spectrum.get("m/z array", []))
                intensity_arr = np.asarray(spectrum.get("intensity array", []))
                if mz_arr.size == 0:
                    continue
                tic = float(intensity_arr.sum())
                entries.append((precursor_mz, tic, list(zip(mz_arr.tolist(), intensity_arr.tolist()))))

    elif suffix == ".mzxml":
        from pyteomics import mzxml
        with mzxml.read(str(raw_path)) as reader:
            for spectrum in reader:
                if spectrum.get("msLevel") != 2:
                    continue
                precursor_mz = _get_precursor_mz_mzxml(spectrum)
                if precursor_mz is None:
                    continue
                mz_arr = np.asarray(spectrum.get("m/z array", []))
                intensity_arr = np.asarray(spectrum.get("intensity array", []))
                if mz_arr.size == 0:
                    continue
                tic = float(intensity_arr.sum())
                entries.append((precursor_mz, tic, list(zip(mz_arr.tolist(), intensity_arr.tolist()))))

    else:
        raise ValueError(f"Unsupported raw file extension '{suffix}' for {raw_path}")

    entries.sort(key=lambda e: e[0])
    return entries


def lookup_best_ms2(index: list, target_mz: float, tolerance_da: float, min_relative_intensity: float) -> list[tuple[float, float]]:
    """
    In-memory lookup against a preloaded index
    Picks the highest-TIC matching spectrum, same rule PyteomicsMS2SpectrumReader used.
    """
    candidates = [e for e in index if abs(e[0] - target_mz) <= tolerance_da]
    if not candidates:
        return []
    _, _, peaks = max(candidates, key=lambda e: e[1])
    peaks_arr = np.array(peaks)
    base_peak = peaks_arr[:, 1].max()
    if base_peak <= 0:
        return []
    floor = base_peak * min_relative_intensity
    filtered = peaks_arr[peaks_arr[:, 1] >= floor]
    return [(float(mz), float(i)) for mz, i in filtered]