# Voice Assist Improver

Makes Home Assistant's Assist need an LLM less and less.

## Setup

1. In the **Configuration** tab, paste your Anthropic API key, pick the language, and start the app.
2. In Home Assistant, add the **Ollama** integration (Settings → Devices & services → Add integration) with
   the URL `http://<app hostname>:11435`. The hostname is shown on this app's **Info** tab (it looks like
   `xxxxxxxx-voice-assist-improver`).
3. Open the new Ollama agent and set **Instructions** to your short voice prompt, **Control Home Assistant** to
   *No control*, and pick a model (`claude-haiku-5-5` is a good start).
4. In **Settings → Voice assistants**, choose that agent in your pipeline and keep **Prefer handling commands
   locally** on. Only what Assist cannot handle reaches this app.

## The panel

The *Voice Assist* entry in the sidebar shows how many requests needed the LLM each day, which phrases keep
coming back, the spend, and a list of **suggestions** (aliases that would let Assist handle those phrases
locally). Apply a suggestion with *Do it for me* (you confirm first, and can undo), or do it yourself and
mark it done. *Never again* hides a suggestion for good.

## Cost and privacy

- Requests go to the Anthropic API with your key. Set a spending limit in the Anthropic Console as well.
- The estimated spend is shown in the panel; the monthly cap stops AI calls when reached.
- What people say is stored locally in this app's data folder and deleted after the retention period.
- Locks, alarms, doors and gates are never given aliases or suggestions.

## Prompt

A file named `voice_prompt.md` in this app's config folder replaces the built-in voice prompt.
