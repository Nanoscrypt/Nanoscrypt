from pydantic import BaseModel, Field

class PlannerDecision(BaseModel):
    action: str = Field(..., description="Action to take: generate_tool, reuse_tool, direct_response, clarify")
    tool_name: str | None = Field(default=None, description="Target tool name if action is generate_tool or reuse_tool")
    tool_purpose: str | None = Field(default=None, description="Short summary of what tool should accomplish")
    input_description: str | None = Field(default=None, description="Expectations of the input arguments")
    output_description: str | None = Field(default=None, description="Expectations of the output payload")
    dependencies_hint: list[str] = Field(default_factory=list, description="Third party packages likely needed")
    reuse_existing: bool = Field(default=False, description="Flag indicating if a tool can be reused")
    reasoning: str = Field(..., description="CoT reasoning behind decision")
