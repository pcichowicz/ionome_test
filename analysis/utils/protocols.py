from pathlib import Path
from typing import Protocol
from analysis.context import LCMSContext

# ======== Pipeline =========== #
class PipelineStage(Protocol):
    """
    Every stage (ingestion, feature detection, ...) implements this.
    """

    name: str

    def validate_input(self, context: LCMSContext) -> bool:
        """
        Check prerequisites are present before running. Return False
        (not raise) for "not ready yet"; raise FatalStageError for
        "something is actually wrong".
        """
        ...

    def execute(self, context: LCMSContext) -> LCMSContext:
        """
        Do the work; return the (mutated) context. Raise
        RecoverableStageError or FatalStageError as appropriate.
        """
        ...

    def validate_output(self, context: LCMSContext) -> bool:
        """
        Sanity-check output before moving on to the next stage.
        """
        ...

# ======== System Suitability =========== #
class PrecursorReader(Protocol):
    """
    Reads the set of DDA precursor m/z values selected for MS2 in an mzML file.
    """

    def get_precursor_mzs(self, mzml_path: Path) -> list[float]:
        ...

# ======== Feature Detection =========== #
class FeatureDetector(Protocol):
    def detect_features(
        self, mzml_path: Path, output_path: Path, params: dict
    ) -> list[dict]:
        """
        Run feature detection on mzml_path, write full results to
        output_path (e.g. featureJSON), and return a lightweight summary
        list: [{"mz": ..., "rt": ..., "intensity": ..., "charge": ...}, ...]
        """
        ...

# ======== Library Matching =========== #
class MS2SpectrumReader(Protocol):
    """
    Extracts a single representative MS2 peak list for a given
    precursor m/z
    """

    def get_ms2_spectrum(
        self, mzml_path: Path, precursor_mz: float, precursor_tolerance_da: float
    ) -> list[tuple[float, float]]:
        """
        Return [(mz, intensity), ...] for the best MS2 scan matching
        precursor_mz, or [] if no matching MS2 scan has any peaks.
        """
        ...
