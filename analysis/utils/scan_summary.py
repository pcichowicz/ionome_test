from pathlib import Path
import pandas as pd
from pyteomics import mzml, mzxml

def extract_scan_summary(raw_path: Path) -> pd.DataFrame:
    """
    Parses an mzML or mzXML file (dispatched by extension) and extracts
    per-scan summary fields, NOT full peak arrays:
    scan_id, ms_level, retention_time_min, total_ion_current,
    base_peak_mz, base_peak_intensity, precursor_mz.

    Output schema is identical regardless of input format -- callers
    (ScanSummaryCacheStage, etc.) don't need to know or care which
    format a given sample's raw file was in.
    """
    suffix = raw_path.suffix.lower()
    if suffix == ".mzml":
        return _extract_from_mzml(raw_path)
    elif suffix == ".mzxml":
        return _extract_from_mzxml(raw_path)
    else:
        raise ValueError(
            f"Unsupported raw file extension '{suffix}' for {raw_path} "
            f"-- expected .mzML or .mzXML"
        )

def _extract_from_mzml(mzml_path: Path) -> pd.DataFrame:
    rows = []
    with mzml.read(str(mzml_path)) as reader:
        for spectrum in reader:
            ms_level = spectrum.get("ms level")
            rt = spectrum.get("scanList", {}).get("scan", [{}])[0].get("scan start time")
            precursor_mz = None
            if ms_level == 2:
                precursors = spectrum.get("precursorList", {}).get("precursor", [])
                if precursors:
                    selected = precursors[0].get("selectedIonList", {}).get("selectedIon", [{}])[0]
                    precursor_mz = selected.get("selected ion m/z")
            rows.append({
                "scan_id": spectrum.get("id"),
                "ms_level": ms_level,
                "retention_time_min": rt,
                "total_ion_current": spectrum.get("total ion current"),
                "base_peak_mz": spectrum.get("base peak m/z"),
                "base_peak_intensity": spectrum.get("base peak intensity"),
                "precursor_mz": precursor_mz,
            })
    return pd.DataFrame(rows)

def _extract_from_mzxml(mzxml_path: Path) -> pd.DataFrame:
    rows = []
    with mzxml.read(str(mzxml_path)) as reader:
        for spectrum in reader:
            ms_level = spectrum.get("msLevel")
            rt_raw = spectrum.get("retentionTime")
            rt_min = _normalize_mzxml_rt(rt_raw)
            precursor_mz = None
            if ms_level == 2:
                # mzXML nests precursor info directly under the spectrum,
                # not a precursorList/selectedIonList chain like mzML.
                precursor_mz = spectrum.get("precursorMz", [{}])[0].get("precursorMz") \
                    if spectrum.get("precursorMz") else None
            rows.append({
                "scan_id": spectrum.get("id") or spectrum.get("num"),
                "ms_level": ms_level,
                "retention_time_min": rt_min,
                "total_ion_current": spectrum.get("totIonCurrent"),
                "base_peak_mz": spectrum.get("basePeakMz"),
                "base_peak_intensity": spectrum.get("basePeakIntensity"),
                "precursor_mz": precursor_mz,
            })
    return pd.DataFrame(rows)

def _normalize_mzxml_rt(rt_raw) -> float | None:
    """
    mzXML's retentionTime, via pyteomics, comes back as a `unitfloat`
    already expressed in minutes. No /60 division required.
    """
    if rt_raw is None:
        return None
    return float(rt_raw)