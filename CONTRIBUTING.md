# Contributing

Thanks for helping. Issues and pull requests are welcome; this is a small volunteer project, so answers may take
a few days.

## Before you start

- **Bugs:** open an issue with the app version, your Home Assistant version and install type, and the app log
  (remove keys, tokens and private phrases first).
- **Ideas:** open an issue before a large change so we can agree on the shape. Read
  [docs/DECISIONS.md](docs/DECISIONS.md): several choices were made on purpose (the model proposes and code
  validates; exposure to Assist is the single control; no free-form writes to Home Assistant).

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/pytest
python scripts/sync_addon.py     # after changing anything under src/
```

More in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Pull requests

- Keep them focused, with tests for behavior changes (the suite has no network access: use fakes).
- Anything that writes to Home Assistant must be validated by code, show a plan, and be undoable.
- User-facing text goes through `i18n.py` / `prompts/` and needs English; Portuguese (pt-BR) if you can.
- Add a line to `voice_assist_improver/CHANGELOG.md` and bump `version` in `config.yaml` for user-visible
  changes. CI runs lint, tests and the app-copy check.

## Adding a language

Add `prompts/voice.<lang>.md`, the strings in `i18n.py`, the app translations in
`voice_assist_improver/translations/<lang>.yaml`, and the panel strings in `web/index.html`.

## Adding an AI provider

Implement the `Backend` protocol in `backends/` (stream text, tool calls and results) and register it in
`backends/__init__.py`. Prices and the model list are provider-specific and live next to the backend.
