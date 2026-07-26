from typing import Any

import structlog
from pydantic import BaseModel, Field

from nanoscrypt.models.session import Session

logger = structlog.get_logger()


class PipelineStep(BaseModel):
    tool_name: str
    input_mapping: dict[str, str] = Field(
        default_factory=dict
    )  # parameter -> key in prior output dict
    condition: str | None = (
        None  # code/logic string or lambda name, executed via simple check
    )


class Pipeline(BaseModel):
    name: str
    steps: list[PipelineStep] = Field(default_factory=list)
    error_strategy: str = "fail_fast"  # fail_fast, continue, retry


class PipelineExecutor:
    """Orchestrates multi-tool execution pipelines where outputs flow into succeeding tool inputs."""

    def __init__(self, orchestrator: Any):
        self.orchestrator = orchestrator

    async def execute(
        self, pipeline: Pipeline, session: Session, initial_inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Runs the pipeline steps sequentially, passing outputs as parameters."""
        log = logger.bind(pipeline=pipeline.name, session_id=session.id)
        log.info("pipeline_execution_started", steps_count=len(pipeline.steps))

        pipeline_outputs: dict[str, Any] = initial_inputs.copy()
        step_results = []

        for idx, step in enumerate(pipeline.steps):
            log.info("pipeline_step_started", idx=idx, tool_name=step.tool_name)

            # Map input parameters from previous step outputs or literal values
            step_inputs = {}
            for param, source_key in step.input_mapping.items():
                if source_key in pipeline_outputs:
                    step_inputs[param] = pipeline_outputs[source_key]
                else:
                    # Treat source_key as a literal parameter value if it's not a key in pipeline_outputs
                    step_inputs[param] = source_key

            # Build prompt representation of parameters for orchestrator
            import json

            prompt_payload = json.dumps(step_inputs)

            try:
                # Execute single orchestrator task for this step
                res = await self.orchestrator.execute_task(
                    user_prompt=prompt_payload, session=session
                )

                step_results.append(res)

                if res.get("status") != "completed":
                    log.error(
                        "pipeline_step_failed",
                        idx=idx,
                        tool_name=step.tool_name,
                        error=res.get("error"),
                    )
                    if pipeline.error_strategy == "fail_fast":
                        return {
                            "status": "failed",
                            "failed_step": idx,
                            "tool_name": step.tool_name,
                            "error": res.get("error"),
                            "step_results": step_results,
                        }

                # Parse step output
                raw_out = res.get("output")
                try:
                    # If step returns JSON dict, parse and merge
                    parsed_out = json.loads(str(raw_out))
                    if isinstance(parsed_out, dict):
                        pipeline_outputs.update(parsed_out)
                except Exception:
                    pass

                # Keep raw output in standard location
                pipeline_outputs[f"step_{idx}_output"] = raw_out
                pipeline_outputs[step.tool_name] = raw_out

            except Exception as e:
                log.error(
                    "pipeline_step_exception",
                    idx=idx,
                    tool_name=step.tool_name,
                    error=str(e),
                )
                if pipeline.error_strategy == "fail_fast":
                    return {
                        "status": "failed",
                        "failed_step": idx,
                        "tool_name": step.tool_name,
                        "error": str(e),
                        "step_results": step_results,
                    }

        log.info("pipeline_execution_completed")
        return {
            "status": "completed",
            "outputs": pipeline_outputs,
            "step_results": step_results,
        }
