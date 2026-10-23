# Voice Assist Improver

**Faz o Assist do Home Assistant precisar cada vez menos de um LLM.**

[![License](https://img.shields.io/github/license/fdaneluzzi/voice-assist-improver)](LICENSE)
[![Release](https://img.shields.io/github/v/release/fdaneluzzi/voice-assist-improver)](https://github.com/fdaneluzzi/voice-assist-improver/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/fdaneluzzi/voice-assist-improver/ci.yml?branch=main&label=CI)](https://github.com/fdaneluzzi/voice-assist-improver/actions/workflows/ci.yml)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-fdaneluzzi-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/fdaneluzzi)

[![Adicionar repositório ao meu Home Assistant][badge]][add-repo]

[badge]: https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg
[add-repo]: https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Ffdaneluzzi%2Fvoice-assist-improver

O Assist trata na hora, localmente e de graça os comandos que entende. O que ele não entende pode cair num LLM:
poderoso, mas lento, pago e necessário de novo toda vez que alguém pede a mesma coisa do mesmo jeito. O Voice
Assist Improver é esse fallback e também **aprende com ele**: registra o que o Assist não conseguiu tratar e
sugere as mudanças que fazem o Assist resolver sozinho da próxima vez.

![O painel, com dados de exemplo](docs/images/panel.png)

*O painel dentro do Home Assistant (dados de exemplo): pedidos que precisaram do LLM por dia e sugestões para revisar.*

> **Versão inicial.** Testada pelo autor no Home Assistant OS. Espere arestas e, por favor, reporte.
> Sem afiliação com o Home Assistant, a Nabu Casa ou qualquer fornecedor de IA.

## Como funciona

1. **Responde o fallback.** Para o Home Assistant ele parece um servidor Ollama, então nada é instalado dentro
   do HA. Ele chama a API da Anthropic com a sua chave, com ferramentas para ler e controlar as entidades que
   você expôs ao Assist e com o prompt que você escolher.
2. **Ensina o Assist.** Uma vez por dia lê os fallbacks recentes e propõe melhorias, que você revisa num painel
   dentro do Home Assistant.

O número que importa está no painel: **quantos pedidos precisaram do LLM por dia, e quantos eram frases que ele
já tinha visto.** Se as sugestões funcionam, ele cai.

## Sugestões

| Tipo | Exemplo | O que o *Faça por mim* cria |
|---|---|---|
| **Apelido** | "pendente da sala" é outro nome de *Sala Pendente* | o apelido na entidade (o nome original continua valendo) |
| **Automação** | "luz baixa" deixa as luzes da sala a 30 % | uma automação com gatilho por frase |
| **Cena** | "modo cinema" | uma cena e uma frase que a ativa |
| **Dica** | conselho que você mesmo executa | nada |

O modelo só *propõe*. O código valida cada proposta ao guardá-la e de novo logo antes de aplicar. Você sempre vê
o plano e confirma, toda mudança vai para um registro de auditoria e **Desfazer** remove o que foi criado.
*Dispensar* esconde a sugestão por um tempo; *Nunca mais* esconde para sempre.

## Requisitos

- Home Assistant OS ou Supervised (roda como app). Em Container ou Core, dá para rodar como contêiner comum com
  um token de longa duração; veja a [documentação](voice_assist_improver/DOCS.md).
- A integração **Model Context Protocol Server**, por onde o agente de voz lê e controla a casa.
- As entidades que você quer controlar por voz, **expostas ao Assist**. O app não enxerga mais nada.
- Uma **chave de API da Anthropic**, criada no Console, de preferência num workspace próprio com limite de gasto
  baixo.

## Instalação

1. Clique no botão acima (ou Configurações → Apps → Loja de apps → ⋮ → Repositórios e adicione
   `https://github.com/fdaneluzzi/voice-assist-improver`).
2. Instale o **Voice Assist Improver**, cole a chave na aba **Configuração** e inicie.
3. Adicione a integração **Ollama** apontando para o app e escolha-a no seu pipeline de voz, com *Preferir
   tratar comandos localmente* ligado. Os passos exatos estão em [voice_assist_improver/DOCS.md](voice_assist_improver/DOCS.md).

## Opções

| Opção | Padrão | |
|---|---|---|
| `anthropic_api_key` | | Sua chave de API |
| `anthropic_workspace_id` | | Só se a chave não estiver ligada a um workspace |
| `language` | `en` | `en` ou `pt-BR`: prompt embutido, mensagens faladas e painel |
| `model` | `claude-haiku-5-5` | Modelo das respostas de voz. Qualquer ID que a sua chave possa usar |
| `analysis_model` | `claude-sonnet-5-5` | Modelo da análise diária |
| `monthly_budget_usd` | `5` | Gasto estimado que interrompe as chamadas de IA no mês. `0` desliga o teto |
| `web_search` | `false` | Deixa o modelo pesquisar na web |
| `voice_tool_denylist` | `[]` | Nomes de ferramentas escondidas do agente de voz (padrões como `light__*`) |
| `retention_days` | `30` | Por quanto tempo os pedidos gravados são mantidos |
| `analysis_hour` | `4` | Hora local da análise diária (`-1` desliga) |

Para trocar o prompt de voz, coloque um `voice_prompt.md` na pasta de configuração do app. Os modelos são texto
livre de propósito: um modelo novo funciona no dia em que existe, e o painel avisa se o ID não estiver disponível
para a sua chave.

## Custo

Você paga direto à Anthropic. Com o modelo pequeno padrão, um pedido de voz costuma custar uma fração de
centavo, e a análise diária cerca de um centavo. O painel mostra o gasto estimado; o teto mensal é uma proteção,
não uma garantia de cobrança, então defina também um limite de gasto no Console da Anthropic.

## Privacidade e segurança

- **O que sai da sua casa:** a cada fallback, o que foi dito, a conversa até ali e o estado das entidades que o
  modelo consultar vão para a Anthropic. Na análise diária, as frases recentes e os nomes das entidades
  expostas. Nada além disso.
- **O que fica:** os pedidos são guardados localmente na pasta de dados do app e apagados depois de
  `retention_days`.
- **A exposição é o controle.** Uma entidade que você não expôs ao Assist é invisível para o app. Deixe
  alarmes, fechaduras e portões sem expor se não quiser controlá-los por voz. A exposição vale para a entidade
  inteira: expor uma fechadura para perguntar se está trancada também deixa o agente de voz tentar operá-la.
- **Só mudanças validadas.** Automações e cenas criadas só usam uma lista curta de serviços de luzes,
  interruptores, ventiladores, cortinas, clima, mídia e válvulas. Não há serviço de fechadura nem de alarme.
- A busca na web vem desligada: texto da web pode tentar dar ordens a um modelo que também controla a sua casa.
  O prompt embutido manda ignorá-las.

## Limitações

- Um único provedor de IA por enquanto (API da Anthropic). O backend é uma interface, então outros podem entrar.
- Inglês e português do Brasil. Os apelidos por regra de área ("o pendente da sala") existem só em português.
- Ele não conserta o reconhecimento de voz: se a transcrição erra, a frase erra. O painel mostra o que foi
  ouvido para você perceber.
- As sugestões precisam de repetição; com poucos pedidos por dia, espere poucas no começo.

## Contribuindo

Issues e pull requests são bem-vindos. Veja [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) para rodar a partir do
código e [docs/DECISIONS.md](docs/DECISIONS.md) para entender por que ele é assim. A versão em inglês desta
página é o [README.md](README.md).

## Apoie

O Voice Assist Improver é gratuito e mantido no tempo livre. Se ele ajuda você, um cafezinho é bem-vindo, e uma
estrela no repositório também.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-fdaneluzzi-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/fdaneluzzi)

Prefere PIX? Chave aleatória: `aae9a1b1-11e2-4282-a16d-7df8f48ae903`

## Licença

Apache-2.0. Veja [LICENSE](LICENSE).
