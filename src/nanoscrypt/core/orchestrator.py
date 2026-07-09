import json
import structlog
from typing import Any
from nanoscrypt.core.context import ContextBuilder
from nanoscrypt.core.planner import Planner
from nanoscrypt.core.generator import ToolGenerator
from nanoscrypt.core.validator import ToolValidator
from nanoscrypt.core.runtime import RuntimeManager
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.core.versioning import VersionManager
from nanoscrypt.core.repair import RepairLoop
from nanoscrypt.models.session import Session, SessionToolOutput
from nanoscrypt.models.tool import GeneratedTool, ToolManifest

logger = structlog.get_logger()

class Orchestrator:
    """Coordinates the entire tool lifecycle loop: plan -> generate/reuse -> validate -> version -> execute -> record."""

    def __init__(
        self,
        context_builder: ContextBuilder,
        planner: Planner,
        generator: ToolGenerator,
        validator: ToolValidator,
        runtime_manager: RuntimeManager,
        registry: ToolRegistry,
        version_manager: VersionManager,
        repair_loop: RepairLoop | None = None
    ):
        self.context_builder = context_builder
        self.planner = planner
        self.generator = generator
        self.validator = validator
        self.runtime_manager = runtime_manager
        self.registry = registry
        self.version_manager = version_manager
        self.repair_loop = repair_loop
    async def _extract_parameters(self, user_prompt: str, input_schema: dict) -> str:
        """Asks the LLM to extract execution arguments matching the input schema from the user prompt."""
        if not input_schema:
            return "{}"

        # If user_prompt is already a JSON dictionary matching/containing parameters, use it directly
        try:
            parsed = json.loads(user_prompt)
            if isinstance(parsed, dict):
                return user_prompt
        except Exception:
            pass

        system_prompt = (
            "You are a parameter extraction assistant. Your task is to extract arguments "
            "from the user prompt that match the target input schema, returning a JSON dictionary.\n"
            "Respond ONLY with a valid JSON dictionary containing the extracted parameters. "
            "Do not add any markdown formatting or explanation."
        )
        
        user_msg = f"User Prompt: {user_prompt}\nTarget Input Schema: {input_schema}\nJSON Output:"
        
        try:
            # We call the planner's LLM to generate the param dict
            raw_res = await self.planner.llm.generate(
                prompt=user_msg,
                system_prompt=system_prompt,
                temperature=0.0
            )
            raw_res = raw_res.strip()
            if raw_res.startswith("```json"):
                raw_res = raw_res[7:]
            if raw_res.startswith("```"):
                raw_res = raw_res[3:]
            if raw_res.endswith("```"):
                raw_res = raw_res[:-3]
            raw_res = raw_res.strip()
            
            # Verify it is valid JSON
            json.loads(raw_res)
            return raw_res
        except Exception as e:
            logger.warning("orchestrator_parameter_extraction_failed", error=str(e), fallback="{}")
            return "{}"

    async def execute_task(
        self, 
        user_prompt: str, 
        session: Session,
        pre_execute_hook = None
    ) -> dict[str, Any]:
        log = logger.bind(session_id=session.id)
        log.info("orchestrator_task_execution_started", prompt=user_prompt)

        # 1. Search existing tools in registry for context assembly
        # For simplicity, pass empty list or look up some tools
        all_tools = await self.registry.search("")
        serialized_tools = []
        for t in all_tools:
            serialized_tools.append({
                "name": t.name,
                "purpose": t.purpose,
                "input_schema": t.input_schema,
                "output_schema": t.output_schema,
                "success_rate": t.success_rate
            })

        # 2. Build Context Prompt
        assembled_prompt = self.context_builder.assemble(
            user_prompt=user_prompt,
            session=session,
            registered_tools=serialized_tools
        )

        # 3. Call Planner
        decision = await self.planner.decide(assembled_prompt)
        log.info("orchestrator_planner_decision", action=decision.action)

        if decision.action == "direct_response":
            return {
                "status": "completed",
                "action_taken": "direct_response",
                "response": decision.reasoning
            }

        if decision.action == "clarify":
            return {
                "status": "clarification_needed",
                "action_taken": "clarify",
                "response": decision.reasoning
            }

        tool_name = decision.tool_name
        if not tool_name:
            return {
                "status": "error",
                "message": "Planner requested tool action but failed to name the tool."
            }

        target_tool = None
        version_number = 1

        # 4. Handle Tool Reuse or Generation
        if decision.action == "reuse_tool" or decision.reuse_existing:
            db_tool = await self.registry.get(tool_name)
            if db_tool:
                log.info("orchestrator_reusing_tool", tool_name=tool_name, version=db_tool.current_version)
                
                # Fetch tool files from the VersionManager storage directory
                v_dir = self.version_manager.get_version_directory(tool_name, db_tool.current_version)
                if v_dir and (v_dir / "tool.py").exists():
                    code = (v_dir / "tool.py").read_text(encoding="utf-8")
                    reqs = (v_dir / "requirements.txt").read_text(encoding="utf-8").splitlines() if (v_dir / "requirements.txt").exists() else []
                    readme = (v_dir / "README.md").read_text(encoding="utf-8") if (v_dir / "README.md").exists() else ""
                    tests = (v_dir / "tests.py").read_text(encoding="utf-8") if (v_dir / "tests.py").exists() else ""
                    
                    target_tool = GeneratedTool(
                        name=db_tool.name,
                        code=code,
                        requirements=reqs,
                        manifest=ToolManifest(
                            name=db_tool.name,
                            language=db_tool.language,
                            entry=db_tool.entry_point,
                            dependencies=db_tool.dependencies,
                            input_schema=db_tool.input_schema,
                            output_schema=db_tool.output_schema
                        ),
                        tests=tests,
                        readme=readme
                    )
                    version_number = db_tool.current_version
                else:
                    log.warning("orchestrator_stored_version_files_missing_regenerating")
            else:
                log.warning("orchestrator_tool_requested_for_reuse_not_found_generating")

        # Fallback to generation if tool wasn't found or requested as new
        if not target_tool:
            log.info("orchestrator_generating_new_tool", tool_name=tool_name)
            target_tool = await self.generator.generate(decision)

            # Validate tool
            val_result = self.validator.validate(target_tool)
            if not val_result.is_valid:
                errors = [iss.message for iss in val_result.issues if iss.severity == "error"]
                log.warning("orchestrator_tool_initial_validation_failed", errors=errors)
                
                if self.repair_loop:
                    log.info("orchestrator_triggering_repair_loop_on_validation_failure")
                    from nanoscrypt.core.runtime import ExecutionResult
                    dummy_failure = ExecutionResult(
                        stdout="",
                        stderr="\n".join(errors),
                        return_code=-1,
                        runtime_ms=0,
                        timed_out=False,
                        workspace_path=self.runtime_manager.get_session_workspace(session.id)
                    )
                    
                    self.runtime_manager.setup_workspace(session.id, target_tool)
                    self.runtime_manager.create_virtual_env(self.runtime_manager.get_session_workspace(session.id))
                    self.runtime_manager.install_dependencies(self.runtime_manager.get_session_workspace(session.id))

                    repaired, _ = await self.repair_loop.repair_tool(
                        session_id=session.id,
                        tool=target_tool,
                        failure_result=dummy_failure,
                        tool_purpose=decision.tool_purpose or "utility"
                    )
                    if repaired:
                        target_tool = repaired
                        # Re-validate repaired tool
                        val_result = self.validator.validate(target_tool)
                    else:
                        return {
                            "status": "failed",
                            "action_taken": "validation",
                            "errors": errors
                        }
                else:
                    return {
                        "status": "failed",
                        "action_taken": "validation",
                        "errors": errors
                    }

            # Update formatted code
            if val_result.formatted_code:
                target_tool.code = val_result.formatted_code

            # Version tool snapshot on disk
            version_number = self.version_manager.create_version(
                tool_name=tool_name,
                code=target_tool.code,
                requirements=target_tool.requirements,
                manifest=target_tool.manifest.model_dump(),
                tests=target_tool.tests,
                readme=target_tool.readme,
                prompt=user_prompt
            )

            # Register in database
            await self.registry.register(
                tool=target_tool,
                code_hash=self.version_manager.diff(tool_name, version_number, version_number) or "initial",
                prompt_used=user_prompt
            )

        # Check security access indicators and invoke pre-execution hook
        if pre_execute_hook:
            scan_res = self.validator.scan_resource_access(target_tool.code)
            if scan_res["file_access"] or scan_res["network_access"]:
                log.info("orchestrator_triggering_security_approval_hook", scan=scan_res)
                # Handle potential sync/async callbacks
                import inspect
                if inspect.iscoroutinefunction(pre_execute_hook):
                    approved = await pre_execute_hook(tool_name, scan_res)
                else:
                    approved = pre_execute_hook(tool_name, scan_res)

                if not approved:
                    log.warning("orchestrator_execution_denied_by_user")
                    return {
                        "status": "denied",
                        "action_taken": "execute_tool",
                        "error": "Execution denied by user due to resource access permissions."
                    }

        # 5. Execute Tool inside Runtime Sandbox
        log.info("orchestrator_setting_up_runtime", tool_name=tool_name)
        self.runtime_manager.setup_workspace(session.id, target_tool)
        self.runtime_manager.create_virtual_env(self.runtime_manager.get_session_workspace(session.id))
        self.runtime_manager.install_dependencies(self.runtime_manager.get_session_workspace(session.id))

        log.info("orchestrator_executing_tool_run", tool_name=tool_name)
        # Extract arguments matching the input schema from the user prompt
        tool_input = await self._extract_parameters(
            user_prompt=user_prompt,
            input_schema=target_tool.manifest.input_schema if target_tool.manifest else {}
        )

        exec_res = self.runtime_manager.execute_tool(session.id, tool_input)
        success = exec_res.return_code == 0 and not exec_res.timed_out

        if not success and self.repair_loop:
            log.warning("orchestrator_execution_failed_triggering_repair_loop", error=exec_res.stderr)
            repaired_tool, _ = await self.repair_loop.repair_tool(
                session_id=session.id,
                tool=target_tool,
                failure_result=exec_res,
                tool_purpose=decision.tool_purpose or "utility"
            )
            if repaired_tool:
                target_tool = repaired_tool
                log.info("orchestrator_re_executing_after_repair")
                
                # Version tool snapshot on disk
                version_number = self.version_manager.create_version(
                    tool_name=tool_name,
                    code=target_tool.code,
                    requirements=target_tool.requirements,
                    manifest=target_tool.manifest.model_dump(),
                    tests=target_tool.tests,
                    readme=target_tool.readme,
                    prompt=user_prompt
                )

                # Register in database
                await self.registry.register(
                    tool=target_tool,
                    code_hash=self.version_manager.diff(tool_name, version_number, version_number) or "repaired",
                    prompt_used=user_prompt
                )
                
                self.runtime_manager.setup_workspace(session.id, target_tool)
                self.runtime_manager.install_dependencies(self.runtime_manager.get_session_workspace(session.id))
                
                tool_input = await self._extract_parameters(
                    user_prompt=user_prompt,
                    input_schema=target_tool.manifest.input_schema if target_tool.manifest else {}
                )
                
                exec_res = self.runtime_manager.execute_tool(session.id, tool_input)
                success = exec_res.return_code == 0 and not exec_res.timed_out

        output_data = None
        error_msg = None

        if success:
            try:
                wrapped_out = json.loads(exec_res.stdout.strip())
                output_data = str(wrapped_out.get("output"))
            except Exception:
                output_data = exec_res.stdout
        else:
            error_msg = exec_res.stderr or f"Exit code: {exec_res.return_code}"

        # 6. Update database metrics and session run records
        await self.registry.update_stats(
            tool_name=tool_name,
            success=success,
            runtime_ms=exec_res.runtime_ms,
            input_data={"prompt": user_prompt},
            output_data={"result": output_data} if success else None,
            error=error_msg
        )

        session_output = SessionToolOutput(
            tool_name=tool_name,
            version=version_number,
            success=success,
            input_data={"prompt": user_prompt},
            output_data=output_data,
            error=error_msg
        )
        session.history.append(session_output)

        # Cleanup sandbox workspace
        from nanoscrypt.config.settings import settings
        if settings.runtime.cleanup_after:
            self.runtime_manager.cleanup_workspace(session.id)

        log.info("orchestrator_task_execution_completed", success=success)
        return {
            "status": "completed" if success else "failed",
            "action_taken": "execute_tool",
            "tool_name": tool_name,
            "version": version_number,
            "output": output_data,
            "error": error_msg,
            "runtime_ms": exec_res.runtime_ms
        }
