import sys

from core.config_schema import ExperimentConfig, load_experiment_config
from analysis.context import LCMSContext
from analysis.pipeline import LCMSPipeline
from pathlib import Path
from core.settings import settings
from core.ingestion import get_experiment_pk_sync

from analysis.stages.ingestion import MzMLIngestionStage
from analysis.stages.scan_summary import ScanSummaryCacheStage
from analysis.stages.chromatogram_plotting import ChromatogramPlottingStage
from analysis.stages.summary_stats_plotting import SummaryStatsPlottingStage
from analysis.stages.system_suitability import SystemSuitabilityStage
from analysis.stages.blank_qc import BlankQCStage
from analysis.stages.feature_detection import FeatureDetectionStage
from analysis.stages.feature_alignment import FeatureAlignmentStage
from analysis.stages.spectral_purity import SpectralPurityStage
from analysis.stages.adduct_annotation import AdductAnnotationStage, CohortAdductAnnotationStage
from analysis.stages.library_matching import SpectralLibraryMatchingStage, CohortLibraryMatchingStage
from analysis.stages.library_assembly import LibraryAssemblyStage, CohortLibraryAssemblyStage
from analysis.stages.summary_stats_plotting import SummaryStatsPlottingStage
from analysis.stages.export import ExportStage, CohortExportStage
from analysis.utils.json_reader import JSONFeatureReader
from analysis.utils.mzml_parsing import (
PyteomicsPrecursorReader,
PyteomicsFeatureDetector,
PyteomicsSpectralPurityReader,
PyteomicsMS2SpectrumReader
)
from analysis.stages.StatPlots import PLSDAStage, HeatmapClusteringStage, VolcanoPlotStage, XICPlottingStage

def build_pipeline(config: ExperimentConfig, context: LCMSContext) -> LCMSPipeline:
    pipeline = LCMSPipeline()

    if config.dataset_profile == "standards_only":
        stages = _build_standard_only_stages(config, context)
    elif config.dataset_profile == "cohort_with_qc":
        stages = _build_cohort_with_qc_stages(config, context)
    else:
        raise ValueError(f"Unknown dataset_profile: {config.dataset_profile}")

    for stage in stages:
        pipeline.register_stage(stage)
    return pipeline

def run_pipeline_for_study(study_id: str,
                           force_stages: set[str] | None = None,
                           on_stage_event= None) -> LCMSContext:
    config = load_experiment_config(settings.yaml_dir / f"{study_id}.yaml")
    experiment_pk = get_experiment_pk_sync(study_id)
    context = LCMSContext(study_id=study_id,experiment_id=experiment_pk, config=config)
    pipeline = build_pipeline(config, context)
    context.qc_metrics["system_suitability"] = {"skipped": "manual test harness — validated cohort data by hand"}
    return pipeline.run(context, force_stages=force_stages, on_stage_event=on_stage_event)

def _build_standard_only_stages(config: ExperimentConfig, context: LCMSContext):
    return [
        MzMLIngestionStage(mzml_dir = context.mzml_dir),
        ScanSummaryCacheStage(),
        ChromatogramPlottingStage(),
        SystemSuitabilityStage(
            reader = PyteomicsPrecursorReader(),
            ppm_tolerance = config.system_suitability.ppm_tolerance,
            applicable_roles = None
        ),
        FeatureDetectionStage(
            detector=PyteomicsFeatureDetector(),
            output_dir=Path(context.featurejson_dir),
            params=config.feature_detection.model_dump()
        ),
        BlankQCStage(
            reader=JSONFeatureReader(),
            mz_tolerance_ppm=config.blank_qc.mz_tolerance_ppm,
            rt_tolerance_sec=config.blank_qc.rt_tolerance_sec
        ),
        AdductAnnotationStage(
            reader=PyteomicsPrecursorReader(),
            candidate_adducts=config.adduct_annotation.candidate_adducts,
            primary_adduct=config.adduct_annotation.primary_adduct,
            ppm_tolerance=config.adduct_annotation.ppm_tolerance,
        ),
        SpectralPurityStage(
            reader=PyteomicsSpectralPurityReader(),
            min_purity=config.spectral_purity.min_purity
        ),
        SpectralLibraryMatchingStage(
            ms2_reader=PyteomicsMS2SpectrumReader(),
            reference_library_path=config.library_matching.reference_library_path,
            reference_library_format=config.library_matching.reference_library_format,
        ),
        LibraryAssemblyStage(
            reader=JSONFeatureReader()),
        ExportStage()
    ]

def _build_cohort_with_qc_stages(config: ExperimentConfig, context: LCMSContext):
    return [
        MzMLIngestionStage(mzml_dir = context.mzml_dir),
        ScanSummaryCacheStage(),
        ChromatogramPlottingStage(),
        FeatureDetectionStage(detector=PyteomicsFeatureDetector(),
                              output_dir=Path(context.featurejson_dir),
                              params=config.feature_detection.model_dump()),
        FeatureAlignmentStage(mz_tolerance_ppm = config.feature_alignment.alignment_mz_tolerance_ppm,
                              rt_tolerance_sec = config.feature_alignment.alignment_rt_tolerance_sec),
        BlankQCStage(reader= JSONFeatureReader,
                     mz_tolerance_ppm=config.blank_qc.mz_tolerance_ppm,
                     rt_tolerance_sec=config.blank_qc.rt_tolerance_sec,
                     mode="feature_table"),
        CohortAdductAnnotationStage(),
        CohortLibraryMatchingStage(reference_library_path = config.library_matching.reference_library_path,
                                   reference_library_format= config.library_matching.reference_library_format),
        CohortLibraryAssemblyStage(),
        ChromatogramPlottingStage(),
        SummaryStatsPlottingStage(),
        PLSDAStage(),
        HeatmapClusteringStage(),
        VolcanoPlotStage(),
        XICPlottingStage(),
        CohortExportStage(),
    ]


if __name__ == "__main__":
    run_pipeline_for_study(sys.argv[1])