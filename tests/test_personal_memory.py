import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from nanoscrypt.models.database import Base
from nanoscrypt.core.memory import UserPersonalMemory
from nanoscrypt.core.context import ContextBuilder
from nanoscrypt.models.session import Session

@pytest.fixture
async def async_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()

@pytest.mark.asyncio
async def test_user_personal_memory_set_and_get(async_session_factory):
    mem = UserPersonalMemory(async_session_factory)
    
    await mem.set_trait("name", "Balaji")
    await mem.set_trait("designation", "AI Architect")
    await mem.set_trait("favorite_color", "teal")
    
    profile = await mem.get_profile()
    
    assert profile["Name"] == "Balaji"
    assert profile["Designation"] == "AI Architect"
    assert profile["Favorite Color"] == "teal"

@pytest.mark.asyncio
async def test_user_personal_memory_regex_extraction(async_session_factory):
    mem = UserPersonalMemory(async_session_factory)
    
    prompt = "Hi, I'm Balaji. I work as a Senior AI Architect and my favorite color is teal."
    await mem.extract_and_store(prompt)
    
    profile = await mem.get_profile()
    
    assert profile.get("Name") == "Balaji"
    assert "AI Architect" in profile.get("Designation", "")
    assert profile.get("Favorite Color") == "teal"

def test_context_builder_personal_profile_rendering(tmp_path):
    builder = ContextBuilder(workspace_root=tmp_path)
    session = Session(id="test_session", workspace_path="./workspaces/test_session")
    
    personal_profile = {
        "Name": "Balaji",
        "Designation": "Senior AI Architect",
        "Favorite Color": "teal"
    }
    
    prompt = builder.assemble(
        user_prompt="Who am I?",
        session=session,
        registered_tools=[],
        personal_profile=personal_profile
    )
    
    assert "=== USER PERSONAL PROFILE & PREFERENCES ===" in prompt
    assert "- Name: Balaji" in prompt
    assert "- Designation: Senior AI Architect" in prompt
    assert "- Favorite Color: teal" in prompt
