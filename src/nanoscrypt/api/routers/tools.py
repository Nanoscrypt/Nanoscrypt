from fastapi import APIRouter, Depends, HTTPException
from nanoscrypt.api.schemas import ToolResponse
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.api.dependencies import get_registry

router = APIRouter(prefix="/tools", tags=["tools"])

@router.get("", response_model=list[ToolResponse])
async def list_tools(
    query: str = "",
    registry: ToolRegistry = Depends(get_registry)
):
    """
    List or search available tools in the registry.
    Optional query parameter filters tools by name or description.
    """
    tools = await registry.search(query)
    response = []
    for t in tools:
        response.append(ToolResponse(
            name=t.name,
            purpose=t.purpose,
            language=t.language,
            current_version=t.current_version,
            success_rate=t.success_rate,
            usage_count=t.usage_count,
            status=t.status,
            created_at=t.created_at
        ))
    return response

@router.get("/{name}", response_model=ToolResponse)
async def get_tool(
    name: str,
    registry: ToolRegistry = Depends(get_registry)
):
    """
    Get a specific tool's details by its name.
    Returns a 404 error if the tool is not found.
    """
    t = await registry.get(name)
    if not t:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found or inactive in registry.")
    
    return ToolResponse(
        name=t.name,
        purpose=t.purpose,
        language=t.language,
        current_version=t.current_version,
        success_rate=t.success_rate,
        usage_count=t.usage_count,
        status=t.status,
        created_at=t.created_at
    )
