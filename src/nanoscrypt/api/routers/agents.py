from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from nanoscrypt.api.dependencies import get_registry
from nanoscrypt.api.schemas import AgentCreate, AgentPermissionsSchema, AgentResponse
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.models.database import DBAgentDefinition

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentResponse)
async def create_agent(
    payload: AgentCreate, registry: ToolRegistry = Depends(get_registry)
):
    """Registers a new agent role in the persistent registry database."""
    async with registry.session_factory() as session:
        async with session.begin():
            # Check if name unique
            stmt = select(DBAgentDefinition).where(
                DBAgentDefinition.name == payload.name
            )
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Agent with name '{payload.name}' already exists.",
                )

            agent_db = DBAgentDefinition(
                name=payload.name,
                role=payload.role,
                goal=payload.goal,
                backstory=payload.backstory,
                tools=payload.tools,
                permissions=payload.permissions.model_dump(),
            )
            session.add(agent_db)
            await session.flush()

            return AgentResponse(
                name=agent_db.name,
                role=agent_db.role,
                goal=agent_db.goal,
                backstory=agent_db.backstory,
                tools=agent_db.tools,
                permissions=AgentPermissionsSchema(**agent_db.permissions),
                created_at=agent_db.created_at,
            )


@router.get("", response_model=list[AgentResponse])
async def list_agents(registry: ToolRegistry = Depends(get_registry)):
    """Lists all registered agent configurations."""
    async with registry.session_factory() as session:
        stmt = select(DBAgentDefinition)
        res = await session.execute(stmt)
        agents = res.scalars().all()
        response = []
        for a in agents:
            response.append(
                AgentResponse(
                    name=a.name,
                    role=a.role,
                    goal=a.goal,
                    backstory=a.backstory,
                    tools=a.tools,
                    permissions=AgentPermissionsSchema(**a.permissions),
                    created_at=a.created_at,
                )
            )
        return response


@router.get("/{name}", response_model=AgentResponse)
async def get_agent(name: str, registry: ToolRegistry = Depends(get_registry)):
    """Retrieves details of a specific agent role configuration."""
    async with registry.session_factory() as session:
        stmt = select(DBAgentDefinition).where(DBAgentDefinition.name == name)
        res = await session.execute(stmt)
        a = res.scalar_one_or_none()
        if not a:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found.")

        return AgentResponse(
            name=a.name,
            role=a.role,
            goal=a.goal,
            backstory=a.backstory,
            tools=a.tools,
            permissions=AgentPermissionsSchema(**a.permissions),
            created_at=a.created_at,
        )
