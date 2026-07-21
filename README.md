# Nanoscrypt

Nanoscrypt is an enterprise-grade agentic framework designed to dynamically synthesize, validate, version, execute, and reuse custom tools inside secure environments. It integrates role-based agents, guardrails, human-in-the-loop approvals, and a multi-tier memory system.

---

## Key Features

- **Dynamic Tool Synthesis and Self-Repair**: Synthesizes Python tools dynamically based on agent plans, runs sandbox test suites, and executes self-repair loops with exponential backoff on failure.
- **Role-Based Agents and RBAC**: Supports dedicated agent profiles with specific roles, goals, backstories, and fine-grained permissions.
- **Human-in-the-Loop Approvals**: Employs configurable risk-level gating to pause and request authorization for file system operations, network access, or custom operations.
- **Shared Virtual Environment Cache**: Hashes requirements lists to cache and reuse virtual environments globally, reducing execution overhead to less than 500ms.
- **Guardrails Policy Engine**: Statically scans code using AST analysis to block disallowed builtins, imports, and access to unauthorized network domains.
- **Immutable Audit Logging**: Logs LLM tokens, costs, tool executions, and security approvals to construct persistent audit trails.
- **Three-Tier Memory Architecture**: Features Short-term session buffers, Long-term persistent key-value context recall, and Entity memory.
- **Chained Pipelines**: Allows planners to chain multiple synthesized tools into single pipelines, automatically passing preceding outputs as inputs.

---

## Installation

Ensure you have Python 3.10 or higher installed.

Clone the repository and install the package:

```bash
git clone https://github.com/JAi-SATHVIK/Nanoscrypt.git
cd Nanoscrypt
pip install -e .
```

To install development dependencies (testing and linting):

```bash
pip install -e .[dev,cli]
```

---

## Configuration

Initialize the local environment configuration file:

```bash
cp nanoscrypt.toml.example nanoscrypt.toml
cp .env.example .env
```

Configure your LLM provider api keys in the `.env` file, and update `nanoscrypt.toml` to customize settings.

### Configuration Parameters

```toml
[llm]
model = "ollama/qwen2.5-coder"
temperature = 0.2
max_tokens = 131072
max_output_tokens = 8192
retry_on_failure = true
max_retries = 3

[runtime]
timeout_seconds = 30
max_memory_mb = 512
cleanup_after = true
workspace_root = "./workspaces"
venv_cache_dir = "./venv_cache"

[security]
approval_mode = "interactive"
default_risk_threshold = "medium"
blocked_domains = []
allowed_domains = []
```

---

## CLI Usage

### 1. Run Orchestrated Tasks

Submit a task directly to the orchestrator:

```bash
nanoscrypt run "Parse the index.html file and extract all link tags"
```

Configure a custom agent role directly via the CLI:

```bash
nanoscrypt run "Scrape recent tech publications" --agent-name "NewsBot" --agent-role "researcher" --allow-web
```

### 2. Manage Agents

List, create, or delete agent configurations:

```bash
# List all registered agents
nanoscrypt agents list

# Create a new agent profile
nanoscrypt agents create custom_coder --role coder --goal "Write highly optimized Python math utilities"

# Delete an agent
nanoscrypt agents delete custom_coder
```

### 3. Start the API Server

Serve the REST API locally:

```bash
nanoscrypt serve --host 127.0.0.1 --port 8000
```

---

## API Documentation

When the server is running, the interactive OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

### Primary Endpoints

- `POST /api/v1/sessions` - Allocate a new execution workspace session.
- `POST /api/v1/tasks` - Submit a prompt for agent orchestration.
- `GET /api/v1/approvals/pending` - List approval requests currently awaiting human validation.
- `POST /api/v1/approvals/{request_id}/resolve` - Approve or deny a pending operation.
- `GET /api/v1/audit` - View governance audit logs.
- `GET /api/v1/agents` - Query registered agent roles.

---

## Testing

Run the automated test suite:

```bash
pytest tests/ -v
```