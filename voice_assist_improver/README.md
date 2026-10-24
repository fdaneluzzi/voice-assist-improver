# Home Assistant app: Voice Assist Improver

I maintain this app in my spare time: keeping up with Home Assistant changes and testing on real hardware
takes time (and some money, for the AI calls). If it saves you time or makes Assist better at your home, I
would be very grateful for your support!

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-fdaneluzzi-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/fdaneluzzi)
[![GitHub Sponsors](https://img.shields.io/badge/GitHub-Sponsor-EA4AAA?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/fdaneluzzi)

## App information

[![Version](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2Ffdaneluzzi%2Fvoice-assist-improver%2Fmain%2Fvoice_assist_improver%2Fconfig.yaml&query=%24.version&label=version)](https://github.com/fdaneluzzi/voice-assist-improver/blob/main/voice_assist_improver/CHANGELOG.md)
![Ingress](https://img.shields.io/badge/ingress-true-blue)
![Arch](https://img.shields.io/badge/arch-aarch64%2Camd64-green)
[![CI](https://img.shields.io/github/actions/workflow/status/fdaneluzzi/voice-assist-improver/ci.yml?branch=main&label=CI)](https://github.com/fdaneluzzi/voice-assist-improver/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/fdaneluzzi/voice-assist-improver)](https://github.com/fdaneluzzi/voice-assist-improver/blob/main/LICENSE)

If you like it, a star on the [repository](https://github.com/fdaneluzzi/voice-assist-improver) helps a lot.
Thanks!

## About

**Makes Home Assistant's Assist need an LLM less and less.**

Assist handles the commands it understands instantly, locally and for free. Anything it does not understand can
fall back to an LLM: powerful, but slow, paid, and needed again every time someone words the same request the
same way. Voice Assist Improver is that fallback, and it also **learns from it**: it records what Assist could
not handle and suggests aliases, automations and scenes so Assist handles it by itself next time.

![The panel, with example data](https://raw.githubusercontent.com/fdaneluzzi/voice-assist-improver/main/docs/images/panel.png)

*The panel (example data): requests that needed the LLM per day, and suggestions to review.*

## Setup

Open the **Documentation** tab for the full steps. In short:

1. In the **Configuration** tab, paste your Anthropic API key, pick the language, and start the app.
2. Add the **Ollama** integration in Home Assistant with the URL `http://<app hostname>:11435`. The hostname is
   shown on this **Info** tab.
3. Select the new agent in your voice pipeline, with *Prefer handling commands locally* on.
4. Open the panel (**Open web UI** or the sidebar) to review suggestions.

> **Early release.** Tested by its author on Home Assistant OS. Please report problems on
> [GitHub](https://github.com/fdaneluzzi/voice-assist-improver/issues). Not affiliated with Home Assistant,
> Nabu Casa or any AI provider.
