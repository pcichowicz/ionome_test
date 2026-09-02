from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.results import PlotInfo, RunSummary, TablePreview
from core.models import Pipeline
from core.settings import settings

# Cohort-mode's CohortExportStage writes study_id-prefixed filenames;
# standards_only's ExportStage writes plain ones. Every results lookup has
# to check both -- there's no dataset_profile stored directly on Experiment
# to branch on without re-reading the YAML, and checking both is just as
# cheap and doesn't get invalidated if that ever changes.

def resolve_qc_report_path(study_id: str) -> Path | None:
    qc_dir = settings.lcms_results_dir / study_id / "qc_reports"
    for candidate in (qc_dir / f"{study_id}_qc_report.json", qc_dir / "qc_report.json"):
        if candidate.exists():
            return candidate
    return None


def resolve_table_csv_path(study_id: str) -> Path | None:
    library_dir = settings.lcms_results_dir / study_id / "library"
    for candidate in (library_dir / f"{study_id}_feature_table.csv", library_dir / "library.csv"):
        if candidate.exists():
            return candidate
    return None


# Every plots/<category>/ subdirectory the pipeline stages are known to
# write into. Kept as an explicit allowlist (rather than just globbing
# plots_dir/**) so plot serving can validate a requested category without
# accidentally exposing arbitrary files elsewhere in the results dir.
PLOT_CATEGORIES = [
    "chromatograms", "summary_stats", "volcano", "heatmap_clustering", "plsda", "xic",
]


def list_plots(study_id: str) -> list[PlotInfo]:
    plots_dir = settings.lcms_results_dir / study_id / "plots"
    found = []
    for category in PLOT_CATEGORIES:
        category_dir = plots_dir / category
        if not category_dir.is_dir():
            continue
        for png in sorted(category_dir.glob("*.png")):
            found.append(PlotInfo(
                category=category,
                filename=png.name,
                url=f"/studies/{study_id}/results/plots/{category}/{png.name}",
            ))
    return found


def resolve_plot_file(study_id: str, category: str, filename: str) -> Path | None:
    """Used by the plot-serving endpoint. Only ever returns a path that is
    (a) inside an allowlisted category dir under this study's plots dir, and
    (b) actually a .png that exists -- rejects path traversal via filename
    (e.g. '../../something') by checking the resolved path's parent matches
    the expected directory exactly."""
    if category not in PLOT_CATEGORIES:
        return None
    category_dir = (settings.lcms_results_dir / study_id / "plots" / category).resolve()
    candidate = (category_dir / filename).resolve()
    if candidate.parent != category_dir or candidate.suffix != ".png" or not candidate.exists():
        return None
    return candidate


def get_table_preview(study_id: str, n_rows: int = 20) -> TablePreview | None:
    csv_path = resolve_table_csv_path(study_id)
    if csv_path is None:
        return None
    preview_df = pd.read_csv(csv_path, nrows=n_rows)
    total_rows = sum(1 for _ in open(csv_path)) - 1  # header line doesn't count
    return TablePreview(
        columns=list(preview_df.columns),
        rows=preview_df.where(pd.notna(preview_df), None).to_dict(orient="records"),
        total_rows=total_rows,
        download_url=f"/studies/{study_id}/results/table.csv",
    )


async def list_runs(experiment_id: int, session: AsyncSession) -> list[RunSummary]:
    rows = (
        await session.execute(
            select(Pipeline).where(Pipeline.experiment_id == experiment_id).order_by(Pipeline.started_at)
        )
    ).scalars().all()

    by_run: dict[str, list[Pipeline]] = {}
    for row in rows:
        by_run.setdefault(row.run_id, []).append(row)

    summaries = []
    for run_id, steps in by_run.items():
        statuses = {s.status.value for s in steps}
        if "FAILED" in statuses:
            status = "FAILED"
        elif "RUNNING" in statuses:
            status = "RUNNING"
        else:
            status = "SUCCESS"
        summaries.append(RunSummary(
            run_id=run_id,
            status=status,
            started_at=min(s.started_at for s in steps if s.started_at),
            finished_at=max((s.finished_at for s in steps if s.finished_at), default=None),
            n_steps=len(steps),
        ))
    summaries.sort(key=lambda r: r.started_at or "", reverse=True)
    return summaries
