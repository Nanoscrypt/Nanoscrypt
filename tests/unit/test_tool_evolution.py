import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanoscrypt.core.similarity import SimilarityMatcher, EvolutionCandidate
from nanoscrypt.core.versioning import VersionManager
from nanoscrypt.models.plan import PlannerDecision
from nanoscrypt.models.tool import GeneratedTool, ToolManifest
from nanoscrypt.core.mutator import ToolMutator
from nanoscrypt.core.repair import RepairLoop
from nanoscrypt.core.runtime import ExecutionResult


def test_similarity_matcher_candidate_detection():
    registered_tools = [
        {
            "name": "pdf_text_extractor",
            "purpose": "Extracts raw text content from PDF document files",
            "current_version": 1,
            "input_schema": {"pdf_path": "str"},
        },
        {
            "name": "csv_aggregator",
            "purpose": "Calculates column totals and averages from CSV data files",
            "current_version": 2,
            "input_schema": {"file_path": "str", "column": "str"},
        }
    ]

    # Test 1: Evolution candidate for PDF tool (requesting table extraction)
    prompt = "Extract tables and summary statistics from this invoice pdf file"
    candidate = SimilarityMatcher.find_candidate(prompt, registered_tools, min_threshold=0.20)
    assert candidate is not None
    assert candidate.tool_name == "pdf_text_extractor"
    assert candidate.base_version == 1
    assert candidate.similarity_score > 0.20

    # Test 2: Unrelated prompt should find no candidate
    unrelated_prompt = "Play audio mp3 sound file using speaker output"
    cand2 = SimilarityMatcher.find_candidate(unrelated_prompt, registered_tools, min_threshold=0.40)
    assert cand2 is None


def test_version_manager_load_and_lineage(tmp_path):
    vm = VersionManager(tools_dir=tmp_path)
    tool_name = "weather_reporter"

    # Create v1
    v1 = vm.create_version(
        tool_name=tool_name,
        code="def run(city: str) -> dict:\n    return {'temp': 72}\n",
        requirements=["requests"],
        manifest={"name": tool_name, "input_schema": {"city": "str"}, "output_schema": {"temp": "int"}},
        tests="from tool import run\ndef test_run():\n    assert run('SF')['temp'] == 72\n",
        readme="# Weather Reporter v1",
        prompt="Get weather for city",
    )
    assert v1 == 1

    # Create evolved v2 with parent_version=1
    v2 = vm.create_version(
        tool_name=tool_name,
        code="def run(city: str, unit: str = 'F') -> dict:\n    return {'temp': 72, 'unit': unit}\n",
        requirements=["requests"],
        manifest={"name": tool_name, "input_schema": {"city": "str", "unit": "str"}, "output_schema": {"temp": "int", "unit": "str"}},
        tests="from tool import run\ndef test_run():\n    assert run('SF')['temp'] == 72\n    assert run('SF', 'C')['unit'] == 'C'\n",
        readme="# Weather Reporter v2 with units",
        prompt="Add unit support to weather tool",
        parent_version=1,
        change_reason="evolution",
    )
    assert v2 == 2

    # Load version tool
    reconstructed_v1 = vm.load_version_tool(tool_name, version=1)
    assert reconstructed_v1 is not None
    assert "city: str" in reconstructed_v1.code
    assert "unit" not in reconstructed_v1.code

    reconstructed_v2 = vm.load_version_tool(tool_name, version=2)
    assert reconstructed_v2 is not None
    assert "unit: str = 'F'" in reconstructed_v2.code

    # Check lineage
    lineage = vm.get_lineage(tool_name)
    assert len(lineage) == 2
    assert lineage[0]["version"] == 1
    assert lineage[1]["version"] == 2
    assert lineage[1]["parent_version"] == 1
    assert lineage[1]["change_reason"] == "evolution"

    # Check safe rollback
    vm.rollback(tool_name, to_version=1)
    assert vm.get_current_version_number(tool_name) == 1


@pytest.mark.asyncio
async def test_tool_mutator_evolution():
    mock_llm = AsyncMock()
    evolved_dummy = GeneratedTool(
        name="pdf_text_extractor",
        code="def run(pdf_path: str, extract_tables: bool = True) -> dict:\n    return {'text': 'sample', 'tables': []}\n",
        requirements=["pypdf", "openpyxl"],
        manifest=ToolManifest(
            name="pdf_text_extractor",
            purpose="Extract text and tables from PDF",
            input_schema={"pdf_path": "str", "extract_tables": "bool"},
            output_schema={"text": "str", "tables": "list"},
        ),
        tests="from tool import run\ndef test_run():\n    res = run('sample.pdf')\n    assert 'text' in res\n    assert 'tables' in res\n",
        readme="# Evolved PDF Extractor",
    )
    mock_llm.generate_structured.return_value = evolved_dummy

    mutator = ToolMutator(llm=mock_llm)

    base_tool = GeneratedTool(
        name="pdf_text_extractor",
        code="def run(pdf_path: str) -> dict:\n    return {'text': 'sample'}\n",
        requirements=["pypdf"],
        manifest=ToolManifest(name="pdf_text_extractor", purpose="Extract text from PDF"),
        tests="from tool import run\ndef test_run():\n    assert run('sample.pdf')['text'] == 'sample'\n",
        readme="# Base PDF Extractor",
    )

    result = await mutator.evolve(
        base_tool=base_tool,
        base_version=1,
        user_prompt="Add table extraction to pdf parser",
        mutation_goals=["Add extract_tables parameter", "Return tables key in dict"],
    )

    assert result.name == "pdf_text_extractor"
    assert "extract_tables" in result.code
    assert "openpyxl" in result.requirements


def test_dual_suite_regression_runner(tmp_path):
    mock_runtime = MagicMock()
    mock_runtime.get_session_workspace.return_value = tmp_path
    mock_runtime.get_venv_directory.return_value = tmp_path
    
    mock_validator = MagicMock()
    mock_llm = MagicMock()

    repair_loop = RepairLoop(llm=mock_llm, validator=mock_validator, runtime_manager=mock_runtime)

    base_tool = GeneratedTool(
        name="calculator",
        code="def run(a: int, b: int) -> dict:\n    return {'sum': a + b}\n",
        manifest=ToolManifest(name="calculator", purpose="Basic add"),
        tests="from tool import run\ndef test_v1():\n    assert run(2, 3)['sum'] == 5\n",
        readme="# Calculator v1",
    )

    # Compatible evolved tool (Passes both v1 and v2 test suites)
    evolved_compatible = GeneratedTool(
        name="calculator",
        code="def run(a: int, b: int, multiply: bool = False) -> dict:\n    return {'sum': a + b, 'product': a * b if multiply else None}\n",
        manifest=ToolManifest(name="calculator", purpose="Add and multiply"),
        tests="from tool import run\ndef test_v2():\n    assert run(2, 3, multiply=True)['product'] == 6\n",
        readme="# Calculator v2",
    )

    # Mock subprocess run to return success for both suites
    repair_loop.run_tests_in_sandbox = MagicMock(return_value=ExecutionResult(
        stdout="2 passed", stderr="", return_code=0, runtime_ms=10, timed_out=False, workspace_path=tmp_path
    ))

    passed, msg, _ = repair_loop.run_dual_suite_tests("test_sess", base_tool, evolved_compatible)
    assert passed is True
    assert "passed" in msg.lower()

    # Incompatible tool breaking v1 test (simulated failure)
    repair_loop.run_tests_in_sandbox = MagicMock(side_effect=[
        ExecutionResult(stdout="", stderr="AssertionError: KeyError 'sum'", return_code=1, runtime_ms=10, timed_out=False, workspace_path=tmp_path),
        ExecutionResult(stdout="1 passed", stderr="", return_code=0, runtime_ms=10, timed_out=False, workspace_path=tmp_path)
    ])

    passed2, msg2, _ = repair_loop.run_dual_suite_tests("test_sess", base_tool, evolved_compatible)
    assert passed2 is False
    assert "regression failure in suite 1" in msg2.lower()
