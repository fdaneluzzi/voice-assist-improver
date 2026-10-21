# Changelog

## 0.1.3
- Models are free text, not a fixed list; the panel warns when a model is not available to the API key, and
  Home Assistant's model picker lists the models the key can actually use.
- Requests are kept for 30 days by default (was 90).
- The Home Assistant token option for voice is now an advanced option, hidden by default.

## 0.1.2
- The panel shows what the last analysis did (phrases analyzed, new, rejected).
- A request can be deleted from the history (for tests); it no longer counts in metrics or analysis.

## 0.1.1
- The workspace ID option is now listed in the configuration (some API keys need it).

## 0.1.0
- First packaged version: Ollama-compatible endpoint backed by the Anthropic API, Home Assistant tools over MCP,
  panel with metrics, daily analysis with alias suggestions.
