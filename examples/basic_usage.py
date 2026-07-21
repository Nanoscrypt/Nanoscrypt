import asyncio
from nanoscrypt.logging import setup_logging
from nanoscrypt.api.dependencies import get_orchestrator
from nanoscrypt.models.session import Session

async def main():
    # 1. Initialize structured logging
    setup_logging(log_level="INFO", json_output=False)
    
    # 2. Get the Orchestrator
    orchestrator = await get_orchestrator()

    # 3. Create a session context
    session = Session(
        id="example-session-99",
        workspace_path="./workspaces/example-session-99"
    )

    # 4. Define a programmatic task prompt
    prompt = "Create a tool called count_vowels that parses a string and returns a dictionary of vowel counts."

    print(f"Submitting task: '{prompt}'...")
    result = await orchestrator.execute_task(prompt, session)

    print("\n=== EXECUTION RESULT ===")
    print(f"Status: {result.get('status')}")
    print(f"Action Taken: {result.get('action_taken')}")
    if result.get("tool_name"):
        print(f"Generated Tool: {result.get('tool_name')} (v{result.get('version')})")
        print(f"Output: {result.get('output')}")
    if result.get("error"):
        print(f"Error: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())
