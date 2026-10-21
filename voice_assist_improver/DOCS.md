# Voice Assist Improver

Makes Home Assistant's Assist need an LLM less and less.

## Requirements

This app only talks to what Home Assistant offers it, so check these once:

1. **Model Context Protocol Server** integration added (Settings → Devices & services → Add integration). It is
   how the voice agent reads and controls the home.
2. **Entities exposed to Assist** (Settings → Voice assistants → Expose). The app sees only those entities,
   for voice and for suggestions. Do not expose what you do not want voice-controlled.
3. An **Ollama** conversation agent pointing at this app (see Setup) and a pipeline that uses it with
   *Prefer handling commands locally* on.
4. An Anthropic API key, ideally in its own workspace with a spending limit.

The app reaches Home Assistant through the Supervisor, with the access Home Assistant gives every app that
asks for it (`homeassistant_api`). There is nothing to create or paste for that. Without a Supervisor (Home
Assistant Container or Core) run the app as a normal container and set `VAI_HA_URL` and `VAI_HA_TOKEN`
(a long-lived token) instead.

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

## What suggestions can do

- **Alias**: another name for an entity ("pendente da sala"). Reversible.
- **Automation**: a sentence you say triggers a fixed action ("luz baixa" → lights at 30 %). Created as a normal
  automation named *Voice Assist Improver: …* with a sentence trigger. Reversible: *Undo* deletes it.
- **Scene**: a named set of entity states ("modo cinema") plus a sentence that activates it. Reversible.
- **Tip**: advice you carry out yourself.

The model only proposes. Code checks every proposal before it is stored and again before it is applied:
entities must be exposed to Assist and allowed by the policy below, services come from a short allow-list with
range-checked values, sentences are plain words, and nothing from a template is ever written. You always see
the plan and confirm it first.

## Safety policy

By default suggestions only involve lights, switches, climate, covers, fans, valves and media players, and
never entities whose device class is garage, garage door, gate or door. Locks and alarms are not in the list.
Both lists are settings (*Domains suggestions may touch*, *Blocked device classes*) so you can widen or narrow
them. Widening is your decision: a suggestion that can open a gate or unlock a door can be triggered by anyone
who can speak to your assistant.

## Cost and privacy

- Requests go to the Anthropic API with your key. Set a spending limit in the Anthropic Console as well.
- The estimated spend is shown in the panel; the monthly cap stops AI calls when reached.
- What people say is stored locally in this app's data folder and deleted after the retention period.
- Locks, alarms, doors and gates are never given aliases or suggestions.

## Choosing models

The *model* options take any model ID your API key can use, not a fixed list, so new models work without
updating the app. The panel shows a warning if an ID is not available to your key. Start with a small, fast
model for voice (for example `claude-haiku-5-5`) and a more capable one for the daily analysis.

## Advanced

- **Home Assistant token for voice** (`voice_token`) is optional and not shown by default. By default the app
  talks to Home Assistant with the access the Supervisor gives it, which is enough. If you want the voice tools
  to run with fewer privileges, create a user without administrator rights, make a long-lived token for it,
  and add `voice_token: "<token>"` in the configuration (*Edit in YAML*).
- **AI Task.** Home Assistant's Ollama integration can also provide an *AI Task* entity. Do not point it at this
  app: it is built for conversation fallbacks, and those requests would be counted as fallbacks.

## Prompt

A file named `voice_prompt.md` in this app's config folder replaces the built-in voice prompt.
