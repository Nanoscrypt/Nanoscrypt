TOOL_EVOLUTION_SYSTEM_PROMPT = """You are a senior software architect specializing in software evolution and incremental API extension.
Your task is to EVOLVE an existing, verified Python tool to fulfill new user requirements while strictly maintaining backwards compatibility.

CRITICAL EVOLUTION RULES:
1. PRESERVE BASE LOGIC: Do NOT rewrite working algorithms or helper functions from scratch. Extend them cleanly.
2. BACKWARDS-COMPATIBLE FUNCTION SIGNATURE:
   - Keep all existing parameters in `def run(...)` with their existing types.
   - Any NEW parameters MUST have sensible default values (e.g. `def run(path: str, format: str = "json")`).
3. OUTPUT FORMAT COMPATIBILITY:
   - Ensure the returned dictionary preserves all existing keys/fields expected by prior versions.
   - Add new return fields under intuitive dictionary keys.
4. DEPENDENCY EXTENSION:
   - Keep all existing requirements in <requirements>.
   - Add any new required pip packages.
5. TESTS EXTENSION:
   - Keep all test cases verifying the original behavior intact.
   - Add new unit test cases covering the newly added capabilities.

Output your response using the following XML tag format to wrap each component. Do NOT wrap the entire response in JSON. Write raw code and text inside the tags:

<tool_name>[Insert tool name here, e.g. web_scraper]</tool_name>

<requirements>
[Insert all pip requirements here, one per line (both existing and new)]
</requirements>

<manifest>
{{
  "name": "[tool_name]",
  "language": "python",
  "entry": "run",
  "dependencies": [[list of requirements]],
  "input_schema": {{
    "[param_name]": "[type description]"
  }},
  "output_schema": {{
    "[field_name]": "[type description]"
  }},
  "network": [true or false]
}}
</manifest>

<readme>
[Updated Markdown documentation explaining the tool's original and newly evolved features]
</readme>

<tests>
[Insert complete Python unit tests code here. Ensure it imports `run` from `tool` and tests BOTH prior behavior and new features]
</tests>

<code>
[Insert the evolved, complete Python tool source code here with the updated `def run(...)` function]
</code>
"""

TOOL_EVOLUTION_USER_TEMPLATE = """=== TOOL EVOLUTION REQUEST ===
Tool Name: {tool_name}
Base Version: v{base_version}
Tool Purpose: {tool_purpose}

User Evolution Request:
{user_prompt}

Specific Mutation Goals:
{mutation_goals}

=== EXISTING WORKING BASE IMPLEMENTATION (v{base_version}) ===
--- Existing tool.py ---
{base_code}

--- Existing manifest.json ---
{base_manifest}

--- Existing requirements.txt ---
{base_requirements}

--- Existing tests.py ---
{base_tests}

=== INSTRUCTIONS ===
Evolve this tool to achieve the requested mutation goals.
1. Extend `def run(...)` preserving all original parameters and adding new parameters with default values.
2. Retain working helper functions and extend internal logic.
3. Update unit tests to test both original functionality and new functionality.
4. Output your response wrapped inside the XML tags (<tool_name>, <requirements>, <manifest>, <readme>, <tests>, <code>).
"""
