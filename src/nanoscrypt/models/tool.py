from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ToolManifest(BaseModel):
    name: str = Field(..., description="The name of the tool")
    language: str = Field("python", description="The programming language of the tool, usually python")
    entry: str = Field("tool.py", description="The entry point file name, usually tool.py")
    dependencies: list[str] = Field(
        default_factory=list, description="List of third-party pip dependencies"
    )
    input_schema: dict[str, str] = Field(
        default_factory=dict, description="Map of input parameter names to their type descriptions"
    )
    output_schema: dict[str, str] = Field(
        default_factory=dict, description="Map of output field names to their type descriptions"
    )
    network: bool = Field(False, description="Flag indicating if the tool requires network/web access")


class ToolFile(BaseModel):
    filename: str
    content: str


class GeneratedTool(BaseModel):
    name: str = Field(..., description="The name of the tool matching the plan")
    code: str = Field(
        ...,
        description="The complete Python source code implementation of the tool. Must define the run(...) entry point function with correct type hints.",
    )
    requirements: list[str] = Field(
        default_factory=list,
        description="List of pip package requirements, one per line (e.g. ['requests>=2.28', 'BeautifulSoup4'])",
    )
    manifest: ToolManifest = Field(..., description="The metadata manifest of the tool")
    tests: str = Field(
        ...,
        description="The complete Python unit tests code for the tool, verifying run() functionality",
    )
    readme: str = Field(
        ...,
        description="A brief Markdown README documentation file describing the tool's usage",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
