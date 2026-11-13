# Build prompts

These files drive the AI-agent build of EcoChain Copilot. All are in force together.

| File | Purpose | Priority |
|---|---|---|
| ECOCHAIN_MASTER_PROMPT.md | Full spec: locked decisions, contracts, Phases 0-13, standards, 14-item acceptance checklist | Base |
| ECOCHAIN_ADDENDUM_LIVE_DATA.md | Live external data: retrofits R1-R4, new Verifier rules, enrich node, Phase 14, checklist items 15-20 | Wins over master on its topics |
| RESUME_PROMPT.md | Recovery protocol, quota rules, ordering changes | Wins on ordering, recovery, quota |
| FINISH_PROMPT.md | Docker environment, honest gates, Phases 9-14 execution | Wins on environment and evidence rules |

If two files conflict, the more specific one above wins, and the conflict is recorded in docs/DECISIONS.md.
