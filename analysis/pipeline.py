from __future__ import annotations
from dotenv import load_dotenv
import logging
from pathlib import Path
import json
from typing import Callable, Optional

from analysis.context import LCMSContext
from analysis.utils.protocols import PipelineStage
from analysis.utils.cache_utils import load_checkpoint, save_checkpoint
from analysis.utils.timer import timed

load_dotenv()
logger = logging.getLogger("LCMS PIPELINE")

class LCMSPipeline:
    """Registers stages, then runs them in order over a context."""

    def __init__(self) -> None:
        self._stages: list[PipelineStage] = []

    def register_stage(self, stage: PipelineStage) -> "LCMSPipeline":
        self._stages.append(stage)
        return self

    def run(self,
            context: LCMSContext,
            force_stages: set[str] | None = None,
            on_stage_event: StageEventCallback | None = None) -> LCMSContext:
        """
        force_stages: rerun stage even if cache matches, {*} forces all stages
        """
        for stage in self._stages:
            print(f"Running stage: {stage._name}")
            force = bool(force_stages) and ("*" in force_stages or stage._name in force_stages)
            context = self.run_stage(stage, context, force=force, on_stage_event=on_stage_event)
            print("")
        return context

    @timed(lambda self, stage, context, *a, **kw: f"[{context.study_id}] {stage._name}")
    def run_stage(self,
                  stage: PipelineStage,
                  context: LCMSContext,
                  force: bool = False,
                  on_stage_event: StageEventCallback | None = None) -> LCMSContext:
        """
        Run a single stage with validation, error handling, and logging, and cache checkpoint.

        Kept separate from run() so a single stage can be re-executed on its own.
        """
        if on_stage_event:
            on_stage_event(stage._name, "RUNNING", None)
        logger.info("stage.start", extra={"stage": stage._name})

        if not stage.validate_input(context):
            raise FatalStageError(f"{stage._name}: input validation failed")

        cache_key_fn = getattr(stage, "cache_key", None)
        key: str | None = None

        if cache_key_fn is not None and not force:
            try:
                key = cache_key_fn(context)
                checkpoint = load_checkpoint(context.results_dir, stage._name)
            except Exception as exc:
                # Caching for optimization
                logger.warning(
                    "stage.cache_key_error",
                    extra={"stage": stage._name, "error": str(exc)},
                )
                print(f"  cache check failed for {stage._name} ({exc}) -- running normally")
                key = None
                checkpoint = None

            if key is not None and checkpoint is not None and checkpoint.get("key") == key:
                context.qc_metrics[stage._name] = checkpoint["qc_metrics"]
                if checkpoint.get("log_entry"):
                    context.processing_log.append(checkpoint["log_entry"])

                # Re-write the log file even on a cache hit, so results/logs/ reflects
                # every stage that ran THIS pipeline invocation, cached or not.
                save_stage_log(
                    context.results_dir,
                    stage._name,
                    checkpoint["qc_metrics"],
                    checkpoint.get("log_entry"),
                )

                logger.info("stage.cache_hit", extra={"stage": stage._name})
                print(f"  cached (inputs unchanged) -- skipping {stage._name}")
                if on_stage_event:
                    on_stage_event(stage._name, "SUCCESS", None)
                return context

        try:
            context = stage.execute(context)
        except RecoverableStageError as exc:
            logger.warning(
                "stage.recoverable_error",
                extra={"stage": stage._name, "error": str(exc)},
            )
            context.log_step(stage._name, parameters={}, warnings=[str(exc)])
            if on_stage_event:
                on_stage_event(stage._name, "SUCCESS", str(exc))  # recoverable = stage still "completed"
            return context

        except FatalStageError:
            if on_stage_event:
                on_stage_event(stage._name, "FAILED", str(exc))
            raise
        except Exception as exc:  # deliberate catch-all at the stage boundary
            if on_stage_event:
                on_stage_event(stage._name, "FAILED", str(exc))
            raise FatalStageError(f"{stage._name}: unexpected error: {exc}") from exc

        if not stage.validate_output(context):
            raise FatalStageError(f"{stage._name}: output validation failed")

        # Always persist this stage's log + qc_metrics, regardless of caching support --
        # this is a human-readable audit trail, separate from the cache-hit checkpoint below.
        save_stage_log(
            context.results_dir,
            stage._name,
            context.qc_metrics.get(stage._name),
            context.processing_log[-1] if context.processing_log else None,
        )

        if cache_key_fn is not None:
            try:
                save_key = key if key is not None else cache_key_fn(context)
                log_entry = context.processing_log[-1] if context.processing_log else None
                save_checkpoint(
                    context.results_dir,
                    stage._name,
                    save_key,
                    context.qc_metrics.get(stage._name),
                    log_entry,
                )
            except Exception as exc:
                # Same principle as above: a checkpoint-writing problem
                # should not undo a stage that just completed successfully.
                logger.warning(
                    "stage.checkpoint_save_error",
                    extra={"stage": stage._name, "error": str(exc)},
                )
                print(f"  couldn't save checkpoint for {stage._name} ({exc}) -- will re-run next time")

        logger.info("stage.complete", extra={"stage": stage._name})
        if on_stage_event:
            on_stage_event(stage._name, "SUCCESS", None)
        return context

    def run_by_name(self, stage_name: str, context: LCMSContext) -> LCMSContext:
        """Re-run a single registered stage by name -- for debugging one
        stage at a time without re-running everything before it."""
        for stage in self._stages:
            if stage._name == stage_name:
                return self.run_stage(stage, context)
        raise ValueError(f"No registered stage named {stage_name!r}")

def save_stage_log(results_dir: Path, stage_name: str, qc_metrics: dict | None, log_entry: dict | None) -> None:
    out_dir = results_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"{stage_name}.json", "w") as f:
        json.dump({"stage": stage_name, "qc_metrics": qc_metrics, "log_entry": log_entry}, f, indent=2, default=str)

class StageError(Exception):
    """
    Base class for stage-level errors.
    """

class RecoverableStageError(StageError):
    """
    Stage failed for this input, but the pipeline should continue.

    Example: one standard's expected ion wasn't detected. Log it, flag
    it, move on -- don't kill the whole run over one compound.
    """

class FatalStageError(StageError):
    """
    Stage failed in a way that invalidates the whole run; pipeline stops.

    Example: the reference library file is missing, or every sample
    failed feature detection (instrument/config problem, not a
    single-compound problem)
    """

StageEventCallback = Callable[[str, str, Optional[str]], None]
# args: stage_name, status ("RUNNING" | "SUCCESS" | "FAILED"), error_msg or None