import pytest
from nanoscrypt.core.validator import ToolValidator
from nanoscrypt.models.tool import GeneratedTool, ToolManifest

@pytest.fixture
def validator():
    return ToolValidator()

def test_validator_clean_code(validator):
    code = """def run(data: str) -> dict:
    \"\"\"Docstring clean parse.\"\"\"
    cleaned = data.strip()
    return {"cleaned": cleaned}
"""
    manifest = ToolManifest(name="clean_tool")
    tool = GeneratedTool(
        name="clean_tool",
        code=code,
        requirements=[],
        manifest=manifest,
        tests="",
        readme=""
    )

    result = validator.validate(tool)
    assert result.is_valid is True
    assert len([iss for iss in result.issues if iss.severity == "error"]) == 0

def test_validator_syntax_error(validator):
    code = """def run(data: str) -> dict:
    cleaned = data.strip(
    return {"cleaned": cleaned}
"""
    manifest = ToolManifest(name="syntax_error_tool")
    tool = GeneratedTool(
        name="syntax_error_tool",
        code=code,
        requirements=[],
        manifest=manifest,
        tests="",
        readme=""
    )

    result = validator.validate(tool)
    assert result.is_valid is False
    assert any(iss.stage == "syntax" and iss.severity == "error" for iss in result.issues)

def test_validator_security_violations(validator):
    # Prohibited import test
    code_import = """import os
def run(data: str) -> dict:
    return {"res": os.name}
"""
    tool_import = GeneratedTool(
        name="bad_tool", code=code_import, requirements=[],
        manifest=ToolManifest(name="bad_tool"), tests="", readme=""
    )
    result = validator.validate(tool_import)
    assert result.is_valid is False
    assert any("Blocked import 'os'" in iss.message for iss in result.issues)

    # Prohibited builtin test
    code_builtin = """def run(data: str) -> dict:
    eval(data)
    return {}
"""
    tool_builtin = GeneratedTool(
        name="bad_tool2", code=code_builtin, requirements=[],
        manifest=ToolManifest(name="bad_tool2"), tests="", readme=""
    )
    result = validator.validate(tool_builtin)
    assert result.is_valid is False
    assert any("Blocked builtin call 'eval'" in iss.message for iss in result.issues)

def test_validator_missing_entry_point(validator):
    code = """def parse_stuff(data: str) -> dict:
    return {}
"""
    tool = GeneratedTool(
        name="no_entry", code=code, requirements=[],
        manifest=ToolManifest(name="no_entry"), tests="", readme=""
    )
    result = validator.validate(tool)
    assert result.is_valid is False
    assert any(iss.stage == "entry_point" and iss.severity == "error" for iss in result.issues)

def test_validator_import_not_in_requirements(validator):
    # pandas is imported but not in requirements
    code = """import pandas
def run() -> dict:
    return {}
"""
    tool = GeneratedTool(
        name="test_imports", code=code, requirements=[],
        manifest=ToolManifest(name="test_imports", input_schema={}), tests="", readme=""
    )
    result = validator.validate(tool)
    assert result.is_valid is False
    assert any(iss.stage == "imports" and "pandas" in iss.message for iss in result.issues)

def test_validator_schema_mismatch(validator):
    # Param 'x' in run but not in input_schema
    code = """def run(x: int) -> dict:
    return {}
"""
    tool = GeneratedTool(
        name="test_schema", code=code, requirements=[],
        manifest=ToolManifest(name="test_schema", input_schema={"y": "int"}), tests="", readme=""
    )
    result = validator.validate(tool)
    assert result.is_valid is False
    assert any(iss.stage == "schema_contract" and "Parameter 'x'" in iss.message for iss in result.issues)
    assert any(iss.stage == "schema_contract" and "Schema key 'y'" in iss.message for iss in result.issues)

def test_validator_return_type_mismatch(validator):
    # Annotated with dict, returns bare string
    code = """def run() -> dict:
    return "not a dict"
"""
    tool = GeneratedTool(
        name="test_return", code=code, requirements=[],
        manifest=ToolManifest(name="test_return", input_schema={}), tests="", readme=""
    )
    result = validator.validate(tool)
    # Return consistency issues are warnings, so tool is still valid
    assert result.is_valid is True
    assert any(iss.stage == "return_consistency" and iss.severity == "warning" for iss in result.issues)

def test_validator_dead_code(validator):
    # Unused import and top-level variable
    code = """import math
unused_var = 123
def run() -> dict:
    return {}
"""
    tool = GeneratedTool(
        name="test_dead_code", code=code, requirements=[],
        manifest=ToolManifest(name="test_dead_code", input_schema={}), tests="", readme=""
    )
    result = validator.validate(tool)
    assert result.is_valid is True
    assert any(iss.stage == "dead_code" and "math" in iss.message for iss in result.issues)
    assert any(iss.stage == "dead_code" and "unused_var" in iss.message for iss in result.issues)

def test_validator_complexity(validator):
    # Highly complex function (lots of branches)
    code = """def run(x: int) -> dict:
    if x == 1: pass
    if x == 2: pass
    if x == 3: pass
    if x == 4: pass
    if x == 5: pass
    if x == 6: pass
    if x == 7: pass
    if x == 8: pass
    if x == 9: pass
    if x == 10: pass
    if x == 11: pass
    if x == 12: pass
    if x == 13: pass
    if x == 14: pass
    if x == 15: pass
    if x == 16: pass
    return {}
"""
    tool = GeneratedTool(
        name="test_complexity", code=code, requirements=[],
        manifest=ToolManifest(name="test_complexity", input_schema={}), tests="", readme=""
    )
    result = validator.validate(tool)
    assert result.is_valid is True
    assert any(iss.stage == "complexity" and iss.severity == "warning" for iss in result.issues)

def test_validator_package_mappings():
    class MockLLM:
        async def generate(self, prompt, temperature=0.0):
            if "pymupdf" in prompt and "fitz" in prompt:
                return "yes"
            return "no"

    validator = ToolValidator(llm=MockLLM())
    # fitz is imported, pymupdf is in requirements
    code = """import fitz
def run() -> dict:
    return {}
"""
    tool = GeneratedTool(
        name="test_mappings", code=code, requirements=["pymupdf"],
        manifest=ToolManifest(name="test_mappings", input_schema={}), tests="", readme=""
    )
    result = validator.validate(tool)
    assert result.is_valid is True


