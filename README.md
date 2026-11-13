# EcoChain Copilot

EcoChain Copilot is an enterprise multi-agent compliance copilot that validates supplier compliance documents against environmental and trade regulations. When compliance managers upload supplier certificates or BOMs, the system redacts sensitive data locally, extracts claims, retrieves legal standards, forecasts factory audit-failure risks, and applies deterministic verifier rules. Any uncertain or failing claims pause at a human-review checkpoint before generating a tamper-evident compliance scorecard.

## Quick Start (3 Commands)

Run EcoChain Copilot locally using Docker Compose:

```bash
# 1. Clone & enter repository
cd AgenticAI-main

# 2. Start all services in Demo mode (No login required)
docker compose up -d --build

# 3. Open browser at http://localhost:3000
```

## What Each Screen Does

1. **New check (`/jobs`):** Drag-and-drop document upload interface with factory selection dropdown, one-click compliance verification submission, and quick shortcuts to run predefined sample scenarios.
2. **Live run (`/jobs/[jobId]`):** Real-time vertical timeline displaying each stage of analysis (Redact, Extract, Forecast risk, Find law, Verify, Decide) updated live via Server-Sent Events (SSE).
3. **Scorecard (`/jobs/[jobId]`):** Comprehensive audit scorecard showing overall status, 6-month factory risk probability gauge, rule verdicts, direct PDF evidence bounding box links, and human approval/rejection controls.
4. **Review queue (`/reviews`):** Queue of paused workflows requiring human compliance officer authorization, recording reviewer notes directly to the audit log.

## Demo Mode

When running with `AUTH_ENABLED=false` (default for local demonstration):
- **Authentication:** All authentication guards and login forms are bypassed, automatically scoping sessions to `demo-user` and `demo-tenant`.
- **Extraction Fallback:** Rule-based Heuristic extraction and sidecar fixture fallbacks allow the complete deterministic verifier engine to run without requiring local GPU weights or external cloud API credentials.
- **LLM Provider:** Local `FakeLLM` mock is enabled by default to generate audit explanations while deterministic code handles compliance verdicts.
