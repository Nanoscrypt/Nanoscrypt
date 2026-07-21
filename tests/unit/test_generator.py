import pytest
from typing import Any
from nanoscrypt.core.generator import ToolGenerator
from nanoscrypt.models.plan import PlannerDecision
from nanoscrypt.models.tool import GeneratedTool, ToolManifest
from nanoscrypt.llm.base import LLMProvider

class MockGeneratorLLM(LLMProvider):
    """Stub LLM provider that yields a predicted GeneratedTool output."""

    def __init__(self, output_tool: GeneratedTool):
        self.output_tool = output_tool
        self.prompt_received = None

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        return ""

    async def generate_structured(
        self, 
        prompt: str, 
        response_model: Any, 
        system_prompt: str | None = None, 
        **kwargs: Any
    ) -> Any:
        self.prompt_received = prompt
        return self.output_tool

@pytest.mark.asyncio
async def test_tool_generator():
    expected_manifest = ToolManifest(
        name="pdf_parser",
        dependencies=["pypdf"],
        input_schema={"file_path": "str"},
        output_schema={"text": "str"}
    )
    
    mock_tool = GeneratedTool(
        name="pdf_parser",
        code="def run(file_path: str) -> dict:\n    return {'text': 'content'}",
        requirements=["pypdf"],
        manifest=expected_manifest,
        tests="def test_run():\n    pass",
        readme="# PDF Parser"
    )

    llm = MockGeneratorLLM(mock_tool)
    generator = ToolGenerator(llm=llm)

    decision = PlannerDecision(
        action="generate_tool",
        tool_name="pdf_parser",
        tool_purpose="Extract text from pdf files",
        input_description="Filepath to a PDF",
        output_description="Extracted dictionary details",
        dependencies_hint=["pypdf"],
        reasoning="Generate text extractor"
    )

    result = await generator.generate(decision)

    assert result.name == "pdf_parser"
    assert "pdf_parser" in llm.prompt_received
    assert "Extract text from pdf files" in llm.prompt_received
    assert result.code == mock_tool.code
    assert result.manifest.dependencies == ["pypdf"]
    assert result.requirements == ["pypdf"]
