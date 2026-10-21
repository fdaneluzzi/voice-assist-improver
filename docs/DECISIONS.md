# Decisions

Short records of what was decided and why. Newest at the bottom. Date format: YYYY-MM-DD.

## D1 (2026-10-21): this is a separate, open-source project

It grew out of a personal bridge between Home Assistant and the Claude CLI that runs on a Raspberry Pi
(`ha-claude-bridge`). That bridge keeps running untouched; this project reuses ideas and some code, and is
built for other people to install. License: Apache-2.0. No monetization. Support is best-effort.

## D2: the Anthropic API is the primary, supported backend

Facts that drove this (checked on 2026-10-21 against Anthropic's Legal and compliance page for Claude Code):

- Developers building products should use API key authentication. Anthropic does not permit third-party
  developers to offer Claude.ai login in their apps, to route requests through Free/Pro/Max credentials on
  behalf of users, or to collect, store or intermediate Claude.ai credentials or session tokens.
- An end user signing in to the **unmodified** Claude Code binary with their own subscription is allowed,
  including on a platform that hosts it. Preinstalling or running Claude Code inside a product requires
  Anthropic's Commercial Terms and an unmodified binary.
- Advertised Pro/Max limits assume ordinary, individual use, which a 24/7 automation may exceed.

Consequences:

- The API backend is built first (M1). Cost is small for this workload (a few cents a day with a small
  model), and the app will show spend and support a monthly cap.
- A subscription (OAuth) backend is an **optional, unsupported, at-your-own-risk** mode (M6), designed to stay on
  the permitted side: the app never shows a login screen, never touches tokens or login codes, never bundles
  or modifies the Claude Code binary (the user installs and signs in to it themselves), one person uses one
  subscription, and the docs warn about usage limits. Before publishing, re-read the legal page.
- Do not use "Claude", "Claude Code" or "Anthropic" in the product name or logo. Saying "works with Claude"
  in plain text is fine. The app is provider-agnostic by design; the backend is an interface.

## D3: the entry point is an Ollama-compatible API

Home Assistant's built-in Ollama integration talks to it, so there is nothing to install inside Home
Assistant. Every request that arrives is, by definition, a fallback.

## D4: the app owns prompts, tools and permissions

- Prompts: the caller's system message (the "Instructions" field of the Ollama agent in Home Assistant) is
  honored as the main instructions; a short fixed server-side base covers safety rules. Built-in voice prompts
  exist in English (default) and Portuguese (pt-BR); the user can replace them with a custom file.
- Tools: voice requests receive only voice tools; administrator tools are given only to the scheduled analysis
  and "do it for me". Permission is decided by the app's code, never by prompt text.
- Web search is off by default and is a per-request decision of the app.

## D5: the model proposes, the code validates and applies

Learned the hard way: an LLM that wrote entity aliases directly into Home Assistant dropped the `None` marker
(which means "also answers to its own name") on 50 entities, and they stopped understanding their original
names. Suggestions are validated by deterministic code (safe domain, exposed to Assist, no ambiguity, real
evidence), applied by deterministic executors, verified afterwards and audited. Free-form LLM writes to
Home Assistant are not allowed.

## D6: the learning loop is the product

The value that nothing else provides is the loop that shrinks the fallback. North-star metric: requests that
needed the LLM per day, and how many were phrases already seen. Suggestion lifecycle: new, done, dismissed,
never again (a blocklist enforced in code), with the "done" state verified against Home Assistant.

## D7: bounded sessions, not a day-long session

Conversation continuity comes from short sessions that expire on inactivity plus a compact window of the last
few interactions, not from one session that grows all day (cost, latency, stale state, mixed rooms). The daily
analysis runs from the stored interactions, independently of any session.

## D8: languages

English is the default; Portuguese (pt-BR) is supported. User-facing strings live in `i18n.py` and prompts in
`prompts/`. Language-specific logic (for example the pt-BR "thing in the area" aliases) is explicit and returns
nothing for languages that do not need it.

## D9: privacy and safety defaults

Loopback-only listener by default. Interactions are stored locally with a retention period. Locks, alarms,
garage doors and gates are never given aliases or suggestions. Logs never contain credentials.

## D10 (2026-10-21): Anthropic backend choices

- A manual streaming tool loop (not the SDK tool runner): the tools are discovered from Home Assistant at runtime,
  text must reach the speaker as soon as it is produced, and every tool call and result is recorded.
- The cache breakpoint sits on the built-in voice prompt; the caller's system message comes after it, so a dynamic
  template in Home Assistant never invalidates the cached prefix (tools and base prompt). Tools are sorted by
  name so the prefix is stable.
- Effort is `low` by default (voice latency). Forced tool use is never used. Thinking is left to the model.
- Server-side refusal fallback is on by default but only sent to models that support it; Haiku 5.5 has none.
- Web search is a server tool, off by default, enabled per installation.
- Cost is estimated from the API's usage fields with a price table (see `cost.py`) and enforced by an optional
  monthly cap. Prices in the table must be re-checked against the provider before trusting a cap.
- Not yet verified against the live API (no key yet): the exact request shape comes from the SDK documentation
  and a parameter check against the installed SDK; `smoke ask` is the first real test.
