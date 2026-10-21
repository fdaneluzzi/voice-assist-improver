# Architecture

## Flows

**Voice path (fallback).** Assist could not handle a phrase locally; Home Assistant's Ollama agent sends it
to this app.

```
HA Ollama agent ──POST /api/chat──► ollama_api ──► Backend.stream(request) ──► AI service
                                        │                 │ events: text, tool calls, tool results
                                        │                 ▼
                                        │        voice tool registry (read/control exposed entities)
                                        ▼
                                  Store.add_interaction (utterance, reply, tools, timings, error)
```

**Learning loop (scheduled).** On the configured schedule the app reads the recent interactions and asks the
backend, with a read-only view of Home Assistant, for improvements. The answer is a list of *structured*
suggestions. Deterministic code validates each one, stores it, and shows it in the UI.

**Apply.** The user marks a suggestion done (the app verifies it in Home Assistant), dismisses it, blocks it
forever, or asks the app to do it. "Do it" is a two-step flow: a plan is shown, the user confirms, a
deterministic executor applies it, the result is audited and can be undone.

## Components

| Module | Responsibility |
|---|---|
| `ollama_api.py` | Ollama-compatible endpoints; network filter; streams NDJSON; records every interaction; fails soft (spoken apology) |
| `backends/` | `Backend` interface (events: text, tool call, tool result, done). `echo` for development; `anthropic` next |
| `store.py` | SQLite: interactions, retention, the north-star metric (`fallbacks_per_day`) |
| `prompts/`, `i18n.py` | Built-in voice prompts and messages (en default, pt-BR) |
| `ha/ws.py`, `ha/entities.py` | Home Assistant websocket client; entities exposed to Assist with their aliases |
| `ha/aliases.py` | Validate, add, remove, repair aliases (preserves the `None` marker); audit log |
| `ha/area_aliases.py` | Rule-based pt-BR "thing in the area" aliases |
| `config.py` | `VAI_*` settings; safe defaults |

## Tool registries and permissions

Two registries, owned by the app:

- **Voice tools:** read the state of and control the entities exposed to Assist (through Home Assistant's own
  tool surface), plus optional extras (reminders, web search when enabled). Given to every voice request.
- **Admin tools:** a small set of deterministic, validated operations (set an alias, create a scene, create a
  sentence-triggered automation from a validated schema). Given only to the analysis job and to "do it for me".

A request never receives a tool outside its registry, so permission does not depend on what a prompt says.

## Data (SQLite)

`interactions(id, ts, client, model, backend, utterance, reply, tools JSON, latency_ms, first_text_ms, error)`.
Planned for M3: `suggestions(id, fingerprint, kind, target, phrase, payload JSON, status, created, updated)`
and `blocklist(fingerprint)`. A fingerprint is computed from the suggestion's structured fields, so "never
again" and de-duplication do not depend on free-form model text.

## Packaging (M2)

A Home Assistant app (add-on): `ingress` for the web UI with `panel_admin: true`, `homeassistant_api` for the
Core API through the Supervisor proxy, `options`/`schema` for settings, `aarch64` and `amd64` images,
`backup_exclude` for anything holding secrets. To be validated early: how Home Assistant reaches the app by
hostname on the internal network (so no host port is needed), and whether the Supervisor proxy token is accepted
by Home Assistant's MCP server.

## What is ported from the personal bridge

Ported and adapted in M0: alias validation and application (with the `None` fix), rule-based area aliases, the
Ollama-compatible API surface, the network filter, the recording idea (now SQLite). To port next, adapted to
the backend interface: suggestion analysis, learning notes, reminders, house context, alerts (through Home
Assistant's `notify` instead of Telegram). Not ported: the Claude CLI process manager (the API replaces it).

## Milestones and exit criteria

| | Scope | Exit criterion |
|---|---|---|
| M0 | Skeleton, tests, CI | Tests and lint green; repo private |
| M1 | Anthropic backend, Home Assistant tools, per-request prompts, cost meter | A second pipeline in the author's Home Assistant answers real fallbacks end to end; latency and cost measured; small vs larger model compared on real phrases |
| M2 | App packaging, minimal UI, options | Runs as an app on a small host (the author's mini PC) within its memory budget |
| M3 | Scheduled analysis, suggestion lifecycle, metric dashboard | Fallbacks per day trend down on the author's own usage |
| M4 | Policy layer | No sensitive domain reachable; per-command tool control |
| M5 | "Do it for me" | No destructive change in testing; every change undoable |
| M6 | Optional OAuth backend | Legal page re-read; docs and warnings in place |
| M7 | Closed beta, docs, release | Beta without incidents |
