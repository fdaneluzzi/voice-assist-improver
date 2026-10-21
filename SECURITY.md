# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's private reporting instead: open the
repository's **Security** tab and choose **Report a vulnerability**. Include what you found, how to reproduce it,
and the app version. You will get an answer as soon as the maintainers can; this is a volunteer project.

## What counts

Things that deserve a private report include: a way to make the app act on an entity the user did not expose to
Assist, a way to create an automation or scene outside the validated plan, credentials (API keys, tokens)
appearing in logs, the panel or the API, access to the panel or the Ollama endpoint from outside the networks
the app allows, and prompt-injection paths that lead to unconfirmed changes in Home Assistant.

## Supported versions

Only the latest release receives fixes.

## Good practice for users

- Create the API key in its own workspace with a low spending limit.
- Do not expose alarms, locks or gates to Assist if you do not want them voice-controlled.
- Keep web search off unless you need it.
- When sharing logs in an issue, remove keys, tokens and anything people said that you do not want public.
