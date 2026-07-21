import pytest
from nanoscrypt.core.registry import ToolRegistry
from nanoscrypt.models.tool import GeneratedTool, ToolManifest

@pytest.fixture
def database_url():
    # Use SQLite in-memory database for isolated unit testing
    return "sqlite+aiosqlite:///:memory:"

@pytest.mark.asyncio
async def test_tool_registry_lifecycle(database_url):
    registry = ToolRegistry(database_url)
    
    # 1. Initialize tables
    await registry.initialize_db()

    # 2. Register Tool v1
    manifest = ToolManifest(
        name="xml_converter",
        input_schema={"xml_str": "str", "purpose": "Convert XML payload to JSON dict"},
        output_schema={"json_dict": "dict"}
    )
    tool = GeneratedTool(
        name="xml_converter",
        code="def run(xml_str: str) -> dict: return {}",
        requirements=[],
        manifest=manifest,
        tests="",
        readme=""
    )

    db_tool = await registry.register(
        tool=tool,
        code_hash="sha-v1",
        prompt_used="create xml to json parser",
        change_reason="initial release"
    )

    assert db_tool.name == "xml_converter"
    assert db_tool.current_version == 1
    assert db_tool.usage_count == 0

    # 3. Retrieve tool
    retrieved = await registry.get("xml_converter")
    assert retrieved is not None
    assert retrieved.name == "xml_converter"

    # 4. Keyword Search Test
    results = await registry.search("converter")
    assert len(results) == 1
    assert results[0].name == "xml_converter"

    empty_results = await registry.search("unrelated_keyword")
    assert len(empty_results) == 0

    # 5. Update Stats (Successful run)
    await registry.update_stats(
        tool_name="xml_converter",
        success=True,
        runtime_ms=150,
        input_data={"xml_str": "<node></node>"},
        output_data={"res": "ok"}
    )
    
    updated = await registry.get("xml_converter")
    assert updated.usage_count == 1
    assert updated.success_rate == 1.0

    # 6. Update Stats (Failed run)
    await registry.update_stats(
        tool_name="xml_converter",
        success=False,
        runtime_ms=50,
        input_data={"xml_str": "invalid"},
        error="Parsing error"
    )
    
    updated = await registry.get("xml_converter")
    assert updated.usage_count == 2
    # 1 success out of 2 runs = 50% success rate
    assert updated.success_rate == 0.5
