from datetime import datetime, timezone
from pydantic import BaseModel, Field

class ToolManifest(BaseModel):
    name: str
    language: str = "python"
    entry: str = "tool.py"
    dependencies: list[str] = Field(default_factory=list)
    input_schema: dict[str, str] = Field(default_factory=dict)  # parameter_name -> type_desc
    output_schema: dict[str, str] = Field(default_factory=dict) # field_name -> type_desc
    network: bool = False

class ToolFile(BaseModel):
    filename: str
    content: str

class GeneratedTool(BaseModel):
    name: str
    code: str                      # Contents of tool.py
    requirements: list[str]        # Contents of requirements.txt split by line
    manifest: ToolManifest
    tests: str                     # Contents of tests.py
    readme: str                    # Contents of README.md
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
