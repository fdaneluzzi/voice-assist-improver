# Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
cp .env.example .env     # then fill it in and run: .venv/bin/python -m voice_assist_improver
```

Configuration comes from `VAI_*` environment variables, an optional `.env` file, and, when running as a Home
Assistant app, `/data/options.json`. `.env.example` documents every variable. Never commit `.env`.

## Checks against the real services

```bash
.venv/bin/python -m voice_assist_improver.smoke tools                     # Home Assistant tools (no API key)
.venv/bin/python -m voice_assist_improver.smoke ask "Which lights are on?"   # full round trip, prints cost
```

## The app folder

`voice_assist_improver/` is the Home Assistant app. A Docker build only sees that folder, so its `app/`
subfolder is a generated copy of `src/`. After changing anything under `src/`, run:

```bash
python scripts/sync_addon.py          # CI fails if the copy is out of date (--check)
```

Bump `version` in `voice_assist_improver/config.yaml` and add a line to its `CHANGELOG.md` when you release.

## Layout

See [ARCHITECTURE.md](ARCHITECTURE.md). Design decisions and their reasons are in [DECISIONS.md](DECISIONS.md).
