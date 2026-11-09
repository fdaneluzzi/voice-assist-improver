# Changelog

## 0.2.4
- Fix: the same command is no longer suggested over and over. A suggestion is now identified by the phrase and
  its trigger sentences, not by the entities the model picked that day. A new proposal that shares a trigger
  sentence with an existing one (open, created, dismissed or blocked) is dropped, and "Do it for me" is
  refused when another suggestion already created a command with the same sentence.
- The daily analysis now also receives what was already suggested or created and why recent proposals were
  rejected, so it stops repeating them.
- A command can now act on up to 20 entities per action (was 8), enough for "turn off all the air
  conditioners".

## 0.2.3
- Fix: the assistant no longer "corrects" itself about actions it really did. Home Assistant resends only the
  text of earlier turns, so the model saw "Done" with no action behind it and sometimes claimed it had done
  nothing, or even repeated an action. The app now gives back the tool calls and results of the earlier turns
  of the conversation. If the AI service refuses that history, it answers again from the plain text.
- The voice prompts say that earlier tool calls were really run.
- Tool results are recorded up to 4000 characters (was 600), enough to see which devices failed.

## 0.2.2
- New read-only `GET /ui/api/export` (same access as the panel) with full requests, suggestions and analysis
  runs, for diagnosing the app.
- Requests now keep what the caller sent before the turn (roles and whether tool calls were passed on), and each
  analysis keeps the proposals it rejected and why.

## 0.2.1
- Removed the domain and device-class lists for suggestions. Exposure to Assist is the single control: an entity
  you did not expose is invisible to the app. Automations and scenes still only use a short list of validated
  services (none for locks or alarms).

## 0.2.0
- Suggestions can now be sentence-triggered automations and scenes, not only aliases. Each one is validated,
  shown as a plan, created only after you confirm, and can be undone.

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
