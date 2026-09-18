# LangGraph Orchestrator

Reusable LangGraph development container.

Features:

- Aider
- LangGraph
- LangChain
- FastAPI
- PowerShell 7
- PSScriptAnalyzer

Designed for:

- Planner/Coder/Reviewer workflows
- LiteLLM integration
- Docker-based orchestration
- PowerShell code generation and validation

## Build

docker build -t langgraph-orchestrator:latest .

## Run

docker run -it \
  --name aider \
  -v /srv/shared/projects:/app \
  langgraph-orchestrator:latest
