from pydantic import BaseModel, Field


class PlannerDecision(BaseModel):
    action: str = Field(
        ...,
        description="Action to take: generate_tool, reuse_tool, evolve_tool, direct_response, clarify, execute_pipeline",
    )
    tool_name: str | None = Field(
        default=None,
        description="Target tool name if action is generate_tool, reuse_tool, or evolve_tool",
    )
    base_version: int | None = Field(
        default=None,
        description="Base version number to evolve from if action is evolve_tool",
    )
    mutation_goals: list[str] = Field(
        default_factory=list,
        description="List of specific feature additions/changes when evolving an existing tool",
    )
    similarity_score: float | None = Field(
        default=None,
        description="Similarity match score against candidate tool (0.0 - 1.0)",
    )
    tool_purpose: str | None = Field(
        default=None, description="Short summary of what tool should accomplish"
    )
    input_description: str | None = Field(
        default=None, description="Expectations of the input arguments"
    )
    output_description: str | None = Field(
        default=None, description="Expectations of the output payload"
    )
    dependencies_hint: list[str] = Field(
        default_factory=list, description="Third party packages likely needed"
    )
    reuse_existing: bool = Field(
        default=False, description="Flag indicating if a tool can be reused"
    )
    risk_level: str = Field(
        default="low", description="Assessed risk level: low, medium, high, critical"
    )
    pipeline_steps: list[dict] = Field(
        default_factory=list,
        description="List of pipeline steps if action is execute_pipeline. Each step is a dict with tool_name, input_mapping key-value pairs.",
    )
    reasoning: str = Field(..., description="CoT reasoning behind decision")
    response: str | None = Field(
        default=None,
        description="The actual text response to show the user if action is direct_response or clarify",
    )
