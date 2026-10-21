# Architecture

## Flows

**Voice path (fallback).** Assist could not handle a phrase locally; Home Assistant's Ollama agent sends it to
the app.

```
HA Ollama agent ──POST /api/chat──► ollama_api ──► Backend.stream(request) ──► AI service
                                        │                 │ events: text, tool calls, tool results
                                        │                 ▼
                                        │        voice tool registry ──► Home Assistant MCP server
                                        ▼
                                  Store.add_interaction (utterance, reply, tools, timings, cost, error)
```

**Learning loop (daily, or on demand from the panel).** The analyzer groups the recent interactions by phrase,
adds the entities exposed to Assist, and asks the model for improvements through one tool call whose input is a
structured list. Deterministic code validates every item and stores the survivors as suggestions.

**Apply.** The user sees the plan and confirms. A deterministic executor re-validates against the current home,
writes through Home Assistant (registry for aliases, the configuration API for automations and scenes), verifies
what was written, and records an audit entry. Undo removes exactly what was created. "Dismiss" hides a suggestion
for 30 days; "Never again" is a permanent block.

## Modules

| Module | Responsibility |
|---|---|
| `ollama_api.py` | Ollama-compatible endpoints; network filter (the UI has its own, stricter allow-list); NDJSON streaming; records every interaction; fails soft with a spoken apology |
| `backends/` | `Backend` interface (events: text, tool call, tool result, done). `anthropic_api.py` runs the Messages API tool loop with streaming; `unconfigured.py` speaks "not set up yet" so the app still starts; `echo.py` for development |
| `tools.py`, `ha/mcp.py` | Voice tool registry (cached, sorted for a stable prompt cache, deny-list) over Home Assistant's MCP server; a minimal MCP client |
| `models.py` | Live list of the models the API key can use (cached); nothing about model names is hard-coded |
| `cost.py`, `budget.py` | Token usage, cost estimates per model, monthly spending cap |
| `analysis.py` | Daily analysis: summarize phrases, call the model, validate, store suggestions; the schedule |
| `ha/aliases.py`, `ha/area_aliases.py` | Alias validation and application (preserves the `None` marker), audit log; rule-based area aliases (pt-BR) |
| `ha/automations.py` | Validated plans for sentence-triggered automations and scenes; executors with verification, rollback and undo |
| `ha/ws.py`, `ha/entities.py` | Home Assistant websocket client; the entities exposed to Assist with their aliases |
| `store.py` | SQLite: interactions, suggestions (with their plans and what was created), analysis runs, the north-star metric |
| `ui.py`, `web/index.html` | The panel (served through ingress) and its JSON API: metrics, suggestions, apply/undo, delete a request |
| `config.py` | `VAI_*` settings from environment, `.env` and the app's `/data/options.json`; defaults for running as an app |
| `prompts/`, `i18n.py` | Built-in voice prompts and messages (en default, pt-BR) |
| `smoke.py` | Manual checks against the real services |

## Access and permissions

- **Home Assistant access.** As a Home Assistant app it gets a Supervisor token (`homeassistant_api`) and talks
  to Core through the Supervisor proxy. Outside the Supervisor, a long-lived token is configured instead.
- **Two channels, never mixed.** The voice agent only gets the tools of Home Assistant's MCP server, which covers
  the entities exposed to Assist. The websocket and configuration APIs are used by application code only (the
  analysis and the executors), never handed to a model.
- **Exposure is the control (D11).** The app lists only entities exposed to Assist. On top of that, executors
  accept a short allow-list of services with range-checked values, no templates are ever written, and the user
  confirms every change.

## Data

SQLite in the app's data folder. `interactions` (one row per request, with tools, tokens and cost),
`suggestions` (fingerprint, kind, plan, status, and the ids of what was created in Home Assistant) and
`analysis_runs`. A suggestion's fingerprint comes from its structured fields, so de-duplication and "never
again" do not depend on the model's wording. Interactions are purged after `retention_days`.

## Packaging

`voice_assist_improver/` is the Home Assistant app: `config.yaml` (options, schema, ingress), a `Dockerfile`
on a small Python image, translations, docs, icon. Ingress serves `/ui/` to the admin only; the Ollama endpoint
is reachable on the app network (Core). A Docker build sees only the app folder, so `app/` inside it is a
generated copy of `src/` (`scripts/sync_addon.py`, checked in CI).
