# Voice Assist Improver

**Faz o Assist do Home Assistant precisar cada vez menos de um LLM.**

> Status: **pré-alfa (marco M0)**. O esqueleto roda e é testado, mas ainda não fala com nenhum serviço de IA.
> Não serve para controle de voz de verdade. Sem afiliação com o Home Assistant, a Nabu Casa ou fornecedores de IA.

## A ideia

O Assist trata localmente, na hora e de graça os comandos que entende. O que ele não entende pode cair num
LLM (fallback). O fallback é poderoso, mas é lento, custa dinheiro e é necessário de novo toda vez que alguém
fala a mesma coisa do mesmo jeito.

O Voice Assist Improver fica atrás do agente de conversa **Ollama** do Home Assistant e faz duas coisas:

1. **Responde o fallback**: é um endpoint compatível com Ollama que chama um backend de IA, com ferramentas
   para ler e controlar a casa e prompts que você pode personalizar (inglês por padrão, português incluído).
2. **Ensina o Assist com os próprios fallbacks**: registra cada frase que precisou do LLM e, no horário
   configurado, analisa e sugere melhorias ao Home Assistant (aliases, automações com gatilho por frase,
   cenas). Aplicou a sugestão, a mesma frase deixa de precisar do LLM.

A métrica principal é simples: **quantos pedidos precisam do LLM por dia, e quantos deles são frases que ele já
viu**. Se as melhorias funcionam, esses números caem.

## Princípios

- **O modelo propõe, o código valida e aplica.** Nada é aplicado sem você, e tudo fica registrado.
- **Menor privilégio.** Pedidos de voz só recebem ferramentas de voz; as de administrador existem apenas
  para a análise agendada e para o "faça por mim".
- **A exposição é o controle.** O app só enxerga as entidades que você expôs ao Assist; deixe alarmes, fechaduras e portões sem expor. Automações e cenas criadas usam só serviços validados (nenhum para fechaduras ou alarmes). A busca na web
  fica desligada até você ligar. O endpoint só escuta no loopback até você abrir.
- **Seus dados ficam com você**, guardados localmente, com retenção configurável.
- **Chave de API primeiro.** Veja [docs/DECISIONS.md](docs/DECISIONS.md).

Roadmap e arquitetura: [README.md](README.md) e [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Licença

Apache-2.0.
