# Voice Assist Improver

**Makes Home Assistant's Assist need an LLM less and less.**

> Status: **pre-alpha**. Runs end to end against the real Anthropic API and a real Home Assistant (voice
> fallback, panel, daily analysis with alias suggestions). Packaged as a Home Assistant app for internal
> testing; not published yet. Not affiliated with Home Assistant, Nabu Casa or any AI vendor.

## The idea

Home Assistant's Assist handles the commands it understands locally, instantly and for free. Everything it
cannot understand can fall back to an LLM. That fallback is powerful, but slow, it costs money, and it is
needed again every time someone phrases the same thing the same way.

Voice Assist Improver sits behind the **Ollama** conversation agent of Home Assistant and does two jobs:

1. **Answers the fallback**: it is an Ollama-compatible endpoint that calls an AI backend, with tools to
   read and control the home, and with prompts you can customize (English by default, Portuguese included).
2. **Teaches Assist from its own fallbacks**: it records every phrase that needed the LLM, and on a schedule
   it analyses them and suggests improvements to Home Assistant: aliases for entities, sentence-triggered
   automations, scenes. Apply a suggestion and the same phrase stops needing the LLM.

The north-star metric is simple: **how many requests need the LLM per day, and how many of those are
phrases it already saw**. If the improvements work, those numbers go down.

```
Home Assistant (Assist, "Ollama" agent) ──► Voice Assist Improver ──► AI backend (Anthropic API first)
                                               │
                                               ├─ records every fallback
                                               ├─ analyses them on a schedule
                                               └─ suggests (and, if you ask, applies) improvements
```

## Principles

- **The model proposes, the code validates and applies.** Suggestions are checked by deterministic code
  before anything touches Home Assistant, every change is audited, and nothing is applied without you.
- **Least privilege.** Voice requests only ever get voice tools. Administrator tools exist only for the
  scheduled analysis and the "do it for me" action, never in the voice path.
- **Safe by default.** Locks, alarms and gates are never offered aliases or suggestions. Web search is off
  unless you turn it on. The endpoint listens on loopback until you open it.
- **Your data stays with you.** Interactions are stored locally, with a retention setting.
- **API key first.** The Anthropic API is the supported backend. See [docs/DECISIONS.md](docs/DECISIONS.md)
  for why, and for what the optional, unsupported subscription mode will and will not do.

## Roadmap

| | Milestone | State |
|---|---|---|
| M0 | Skeleton: Ollama-compatible API, recording, storage, prompts (en / pt-BR), alias safety logic, CI | done |
| M1 | Anthropic API backend: tool loop, Home Assistant tools, per-request prompts, cost meter, budget cap | done, validated live |
| M2 | Home Assistant app packaging, web panel (ingress), options | done; first install on a real Home Assistant in progress |
| M3 | Suggestion engine: scheduled analysis, lifecycle (done / dismiss / never again), metric dashboard | alias suggestions done; automations and scenes next |
| M4 | Policy layer: tools per command, sensitive-domain audit | |
| M5 | "Do it for me": plan, confirm, execute, undo | |
| M6 | Optional subscription (OAuth) backend, unsupported and at your own risk | |
| M7 | Closed beta, docs, release | |

Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## What you need in Home Assistant

- The **Model Context Protocol Server** integration (how the voice agent reads and controls the home).
- The entities you want voice-controlled **exposed to Assist**. The app sees nothing else.
- An **Ollama** conversation agent pointing at the app, in a pipeline with *Prefer handling commands locally*.
- An Anthropic API key (ideally in its own workspace with a spending limit).

As a Home Assistant app it reaches Home Assistant through the Supervisor with the standard app access, so there
is no token to create. Details, and what suggestions may and may not touch (a configurable safety policy), are in
[voice_assist_improver/DOCS.md](voice_assist_improver/DOCS.md).

## Install as a Home Assistant app

The repository is a Home Assistant app repository (`repository.yaml`, folder `voice_assist_improver/`). Add its
URL under Settings → Apps → App store → ⋮ → Repositories, or copy the folder to `/addons` for a local install.
Then follow `voice_assist_improver/DOCS.md`. The app source inside that folder is a generated copy: run
`python scripts/sync_addon.py` after changing anything under `src/` (CI checks it).

## Try it from a checkout (needs an Anthropic API key)

```bash
.venv/bin/python -m voice_assist_improver.smoke tools            # Home Assistant tools (no API key needed)
.venv/bin/python -m voice_assist_improver.smoke ask "Which lights are on?"   # full round trip, prints cost
```

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
cp .env.example .env   # then run: .venv/bin/python -m voice_assist_improver
```

## License

Apache-2.0. See [LICENSE](LICENSE).
