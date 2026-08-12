import asyncio
import json
import os
import re
import sys
from pathlib import Path
import structlog
from typing import Any, Dict, List, Optional

from nanoscrypt.config.settings import settings
from nanoscrypt.models.session import Session, SessionToolOutput
from nanoscrypt.models.plan import PlannerDecision

logger = structlog.get_logger()

# System prompt template for the Code-Based Agent
CODE_AGENT_SYSTEM_PROMPT = """You are an expert assistant who can solve any task using code blocks. You will be given a task to solve as best you can.
To do so, you have been given access to a list of tools: these tools are basically Python functions which you can call with code.
To solve the task, you must plan forward to proceed in a series of steps, in a cycle of 'Thought:', 'Code:', and 'Observation:' sequences.

At each step, in the 'Thought:' attribute, you should first explain your reasoning towards solving the task and the tools that you want to use.
Then in the 'Code' attribute, you should write the code in simple Python.
During each intermediate step, you can use 'print()' to save whatever important information you will then need.
These print outputs will then appear in the 'Observation:' field, which will be available as input for the next step.
In the end you must return a final answer using the `final_answer` tool. You will be generating a JSON object with the following structure:
```json
{{
  "thought": "...",
  "code": "..."
}}
```

Here are a few rules you should always follow to solve your task:
1. Use only variables that you have defined!
2. Always use the right arguments for the tools. DO NOT pass the arguments as a dict as in 'answer = wikipedia_search({{'query': "What is the place where James Bond lives?"}})', but use the arguments directly as in 'answer = wikipedia_search(query="What is the place where James Bond lives?")'.
3. Take care to not chain too many sequential tool calls in the same code block, especially when the output format is unpredictable. For instance, a call to wikipedia_search has an unpredictable return format, so do not have another tool call that depends on its output in the same block: rather output results with print() to use them in the next block.
4. Call a tool only when needed, and never re-do a tool call that you previously did with the exact same parameters.
5. Don't name any new variable with the same name as a tool: for instance don't name a variable 'final_answer'.
6. Never create any notional variables in our code, as having these in your logs will derail you from the true variables.
7. You can use imports in your code, but only from standard library modules.
8. The state persists between code executions: so if in one step you've created variables or imported modules, these will all persist.
9. Don't give up! You're in charge of solving the task, not providing directions to solve it.

Available tools you can call inside your python code:
{tools_doc}

def final_answer(answer: Any) -> None:
    \"\"\"Call this function once you have solved the task to return the final answer. This will end the loop.\"\"\"

Now Begin!
"""

class CodeAgentExecutor:
    """Orchestrates the stateful Thought-Code-Observation LLM loop and executes sandbox code with stdio RPC."""

    def __init__(self, orchestrator: Any):
        self.orchestrator = orchestrator

    async def execute(self, user_prompt: str, session: Session, active_agent: Any) -> Dict[str, Any]:
        """Executes the main Thought-Code-Observation loop."""
        log = logger.bind(component="code_agent", session_id=session.id)
        log.info("code_agent_loop_started")

        # 1. Fetch and document all available tools from registry for the system prompt
        all_tools = await self.orchestrator.registry.search("")
        mcp_tools = []
        if hasattr(self.orchestrator, "mcp_manager"):
            for s_name, s_client in self.orchestrator.mcp_manager.servers.items():
                for t in s_client.tools:
                    mcp_tools.append(t)

        tools_doc = ""
        # Document registry tools
        for t in all_tools:
            args_list = []
            if t.manifest and t.manifest.input_schema:
                for arg_name, arg_type in t.manifest.input_schema.items():
                    args_list.append(f"{arg_name}: {arg_type}")
            args_str = ", ".join(args_list)
            tools_doc += f"def {t.name}({args_str}) -> Any:\n    \"\"\"{t.purpose}\"\"\"\n\n"

        # Document MCP tools
        for t in mcp_tools:
            t_name = t.get("name")
            t_purpose = t.get("description", "MCP tool")
            raw_props = t.get("inputSchema", {}).get("properties", {})
            args_list = []
            for arg_name, arg_cfg in raw_props.items():
                arg_type = arg_cfg.get("type", "any") if isinstance(arg_cfg, dict) else "any"
                args_list.append(f"{arg_name}: {arg_type}")
            args_str = ", ".join(args_list)
            tools_doc += f"def {t_name}({args_str}) -> Any:\n    \"\"\"{t_purpose}\"\"\"\n\n"

        # Setup loop variables
        max_iterations = settings.resilience.max_repair_attempts or 10
        history = []
        final_result = None
        state_file_content = []

        system_prompt = CODE_AGENT_SYSTEM_PROMPT.format(tools_doc=tools_doc)

        for iteration in range(1, max_iterations + 1):
            log.info("code_agent_iteration_started", iteration=iteration)

            # Construct message context
            assembled = f"Task:\n{user_prompt}\n\n"
            for turn in history:
                if turn["type"] == "llm":
                    assembled += f"Thought: {turn['thought']}\nCode:\n{turn['code']}\n\n"
                elif turn["type"] == "observation":
                    assembled += f"Observation:\n{turn['content']}\n\n"

            # Call LLM
            try:
                raw_response = await self.orchestrator.planner.llm.generate(
                    prompt=assembled, system_prompt=system_prompt, temperature=0.0
                )
            except Exception as e:
                log.error("code_agent_llm_call_failed", error=str(e))
                return {"status": "failed", "error": f"LLM Call failed: {e}"}

            # Parse JSON
            decision = {}
            try:
                # Find JSON block
                clean_json = raw_response.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()
                decision = json.loads(clean_json)
            except Exception:
                # Fallback parser if not valid JSON
                thought_match = re.search(r"Thought:\s*(.*?)(?=\nCode:|$)", raw_response, re.DOTALL)
                code_match = re.search(r"Code:\s*(.*)", raw_response, re.DOTALL)
                decision = {
                    "thought": thought_match.group(1).strip() if thought_match else "Reasoning...",
                    "code": code_match.group(1).strip() if code_match else ""
                }

            thought = decision.get("thought", "Reasoning...")
            code = decision.get("code", "")

            history.append({"type": "llm", "thought": thought, "code": code})
            log.info("code_agent_thought", thought=thought)

            if not code.strip():
                history.append({"type": "observation", "content": "Error: Empty code block. Please write valid Python code."})
                continue

            # Execute code block in sandbox
            obs, final_result, term = await self._run_sandbox_code(
                code=code,
                session=session,
                state_file_content=state_file_content
            )

            if term:
                log.info("code_agent_loop_completed", success=True)
                return {
                    "status": "completed",
                    "action_taken": "execute_code_agent",
                    "output": final_result
                }

            history.append({"type": "observation", "content": obs})
            log.info("code_agent_observation", observation=obs[:200])

        log.warning("code_agent_max_iterations_reached")
        return {"status": "failed", "error": "Max iterations reached without calling final_answer()"}

    def _dispatch_tool_sync(self, tool_name: str, args: dict, session: Session, loop: asyncio.AbstractEventLoop) -> tuple[Any, bool]:
        """Dispatches tool execution synchronously from the background thread to the main event loop."""
        async def _dispatch():
            target_tool = await self.orchestrator.registry.get(tool_name)
            if target_tool:
                self.orchestrator.runtime_manager.setup_workspace(session.id, target_tool)
                exec_res = self.orchestrator.runtime_manager.execute_tool(
                    session_id=session.id,
                    input_data=json.dumps(args),
                    requirements=target_tool.requirements,
                )
                if exec_res.return_code == 0:
                    wrapped_out = json.loads(exec_res.stdout.strip())
                    return wrapped_out.get("output"), False
                else:
                    return exec_res.stderr, True
            else:
                if hasattr(self.orchestrator, "mcp_manager"):
                    mcp_res = await self.orchestrator.mcp_manager.call_tool(tool_name, args)
                    is_error = mcp_res.get("isError", False)
                    content_list = mcp_res.get("content", [])
                    text_outputs = [c.get("text", "") for c in content_list if c.get("type") == "text"]
                    stdout_str = "\n".join(text_outputs)
                    if not stdout_str and "result" in mcp_res:
                        stdout_str = json.dumps(mcp_res["result"])
                    return stdout_str or "MCP execution complete", is_error
                else:
                    return f"Tool '{tool_name}' not found", True

        future = asyncio.run_coroutine_threadsafe(_dispatch(), loop)
        return future.result()

    async def _run_sandbox_code(self, code: str, session: Session, state_file_content: List[str]) -> tuple[str, Any, bool]:
        """Runs the LLM code block inside the isolated RuntimeManager, handling stdio RPC requests."""
        workspace = self.orchestrator.runtime_manager.get_session_workspace(session.id)
        os.makedirs(workspace, exist_ok=True)

        # 1. Fetch and document all available tools from registry
        all_tools = await self.orchestrator.registry.search("")
        mcp_tools = []
        if hasattr(self.orchestrator, "mcp_manager"):
            for s_name, s_client in self.orchestrator.mcp_manager.servers.items():
                for t in s_client.tools:
                    mcp_tools.append(t)

        helper_code = [
            "import sys",
            "import json",
            "",
            "def call_tool_remote(tool_name, **kwargs):",
            "    req = {'type': 'call_tool', 'name': tool_name, 'arguments': kwargs}",
            "    print(f'__NANOSCRYPT_REQ__:{json.dumps(req)}', flush=True)",
            "    line = sys.stdin.readline()",
            "    if not line:",
            "        raise Exception('Connection lost with orchestrator')",
            "    resp = json.loads(line)",
            "    if resp.get('status') == 'error':",
            "        raise Exception(resp.get('error'))",
            "    return resp.get('output')",
            "",
            "def final_answer(answer):",
            "    req = {'type': 'final_answer', 'answer': answer}",
            "    print(f'__NANOSCRYPT_REQ__:{json.dumps(req)}', flush=True)",
            "    sys.exit(0)",
            ""
        ]

        # Document registry tools
        for t in all_tools:
            args_list = []
            if t.manifest and t.manifest.input_schema:
                for arg_name, arg_type in t.manifest.input_schema.items():
                    args_list.append(f"{arg_name}: {arg_type}")
            param_names = [arg.split(":")[0].strip() for arg in args_list] if args_list else []
            wrapped_args = ", ".join([f"{p}={p}" for p in param_names])
            helper_code.append(f"def {t.name}({', '.join(param_names)}):")
            helper_code.append(f"    return call_tool_remote('{t.name}', {wrapped_args})")
            helper_code.append("")

        # Document MCP tools
        for t in mcp_tools:
            t_name = t.get("name")
            raw_props = t.get("inputSchema", {}).get("properties", {})
            args_list = []
            for arg_name, arg_cfg in raw_props.items():
                arg_type = arg_cfg.get("type", "any") if isinstance(arg_cfg, dict) else "any"
                args_list.append(f"{arg_name}: {arg_type}")
            param_names = [arg.split(":")[0].strip() for arg in args_list] if args_list else []
            wrapped_args = ", ".join([f"{p}={p}" for p in param_names])
            helper_code.append(f"def {t_name}({', '.join(param_names)}):")
            helper_code.append(f"    return call_tool_remote('{t_name}', {wrapped_args})")
            helper_code.append("")

        # Write helper_tools.py in workspace
        with open(workspace / "helper_tools.py", "w", encoding="utf-8") as f:
            f.write("\n".join(helper_code))
        
        # Build tool.py which acts as the execution runner
        # Prepend imports and state variables from previous executions to maintain state persistence
        exec_lines = [
            "from helper_tools import *",
            ""
        ]
        exec_lines.extend(state_file_content)
        exec_lines.append("")
        exec_lines.append("# LLM Code block execution")
        exec_lines.append(code)

        # Write execution script to tool.py
        with open(workspace / "tool.py", "w", encoding="utf-8") as f:
            f.write("\n".join(exec_lines))

        # We construct wrapper.py manually to launch tool.py
        wrapper_code = """
import tool
"""
        with open(workspace / "wrapper.py", "w", encoding="utf-8") as f:
            f.write(wrapper_code)

        # Execute using RuntimeManager python
        requirements = []
        venv_dir = self.orchestrator.runtime_manager.get_venv_directory(requirements)
        self.orchestrator.runtime_manager.create_virtual_env(venv_dir)

        if sys.platform == "win32":
            python_executable = venv_dir / "Scripts" / "python.exe"
        else:
            python_executable = venv_dir / "bin" / "python"

        wrapper_path = (workspace / "wrapper.py").resolve()
        cmd = [str(python_executable.resolve()), str(wrapper_path)]

        # Wrap in CAPSEM if active
        if settings.runtime.capsem_enabled:
            import shutil
            if shutil.which("capsem"):
                cmd = ["capsem"] + cmd

        project_root = Path(".").resolve()
        env = dict(os.environ)
        env["PROJECT_ROOT"] = str(project_root)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(workspace.resolve()), env.get("PYTHONPATH", "")]
        )

        import subprocess
        import concurrent.futures

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(project_root),
            env=env,
        )

        stdout_accum = []
        stderr_accum = []
        loop = asyncio.get_running_loop()

        def _sync_loop():
            final_val = None
            term = False
            try:
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    line = line.strip()

                    if line.startswith("__NANOSCRYPT_REQ__:"):
                        # Process RPC request
                        req_json = line[len("__NANOSCRYPT_REQ__:"):]
                        req = json.loads(req_json)
                        req_type = req.get("type")

                        if req_type == "final_answer":
                            final_val = req.get("answer")
                            term = True
                            break

                        elif req_type == "call_tool":
                            tool_name = req.get("name")
                            args = req.get("arguments", {})

                            out_val, is_err = self._dispatch_tool_sync(tool_name, args, session, loop)
                            if is_err:
                                process.stdin.write((json.dumps({"status": "error", "error": out_val}) + "\n"))
                            else:
                                process.stdin.write((json.dumps({"status": "success", "output": out_val}) + "\n"))
                            process.stdin.flush()
                    else:
                        if line:
                            stdout_accum.append(line)
            except Exception as e:
                stderr_accum.append(f"RPC communication failed: {e}")
            return final_val, term

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            final_answer_value, terminated = await loop.run_in_executor(executor, _sync_loop)

        # Kill process if still running
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        # Capture remaining stderr
        err_data = process.stderr.read()
        if err_data:
            stderr_accum.append(err_data)

        # Save successful execution lines to state_file_content to persist variable state
        if not terminated and len(stdout_accum) > 0:
            # We append the code block to persist variables in scope
            state_file_content.append(code)

        stdout_str = "\n".join(stdout_accum)
        stderr_str = "\n".join(stderr_accum)

        if stderr_str:
            obs = f"Error / Stderr:\n{stderr_str}"
            if stdout_str:
                obs = f"Stdout:\n{stdout_str}\n\n" + obs
        else:
            obs = stdout_str or "Code executed successfully with no output."

        return obs, final_answer_value, terminated
