# Auditoria externa (Codex) — histórico

Auditor: Codex CLI (OpenAI), em modo somente leitura, adversarial. Mais 4 analistas
(engenharia, curadoria, jurídico e produto) na 1ª rodada, em 17/10/2026.

**Resultado:**

- **Curadoria, preço e mensagem:** **APROVADO** na 32ª rodada (17/10/2026).
- **Conferência dos links e agendador** (novos em 19/10): **RESSALVAS sem nenhum
  problema novo** na 37ª e na 38ª rodadas (19/10/2026). Nas palavras do auditor,
  "não identifiquei caminho concreto de bloqueio". As ressalvas dependem de
  coisas fora do código (ver *Riscos aceitos*).
- **Conferir links** (novo em 20/10): **RESSALVAS sem nenhum problema novo** na
  42ª rodada (20/10/2026). O auditor diz que não identificou "novo caminho
  concreto de selo indevido, SSRF, falha no painel ou regressão da rodada".
  Ressalvas: a suíte não foi executada pelo auditor, e falta o teste real com
  links da conta da afiliada (é para isso que a ferramenta existe).

## Por fase

| Rodadas | Tema | O que mudou |
|---|---|---|
| 1–6 | Detector de desconto falso | Preço por dia, promoção vigente fora da referência, cobertura real, piso = 2º menor preço diário, menor leitura da rodada conta. **Lógica de preço fechada na 7ª.** |
| 7–24 | Alegações no título do vendedor ("70% OFF", "19 no crédito"...) | Listas de proibidos, NFKC, texto compacto, analisador de números. Cada rodada achava uma grafia nova. |
| 25–26 | Garantia estrutural | Nenhum número do vendedor no nome publicado; numeral = qualquer caractere numérico do Unicode. |
| 27–28 | Vocabulário de PERMITIDOS | O nome publicado só usa palavras de `robo/vocabulario.py` e das tags. Fechou por construção o que 27 rodadas de lista de proibidos não fecharam. |
| 29 | Painel local | **RESSALVAS** (garantia "se sustenta"): Referer por prefixo, clickjacking e corrida na reserva. Corrigido. |
| 30–31 | Tela única do dia a dia | Preço de produto com variações ("a partir de", "opção mais barata") e avisos de conferência no card. |
| 32 | — | **APROVADO**, sem bloqueio nem regressão. |
| 33 | Conferência dos links + agendador (novos, 19/10) | **REPROVADO** (7): ID por trecho de número, selo antes de o destino abrir, endereço malformado derrubava, "error" em qualquer caminho, HTTPS/porta nos saltos, agendador apagava antes de validar, diagnóstico dizia "TUDO CERTO" sem conferir. Corrigido. |
| 34 | Mesma área | **REPROVADO** (4): selo vinha de endereço do meio do caminho, `?itemid=` em qualquer página, ID "²"/4.301 dígitos derrubava a rodada, marca do agendador lida como curinga do `-like`. Corrigido: vale a página FINAL (outro produto = fora), só caminho de página de produto, IDs ASCII limitados, conferência nunca levanta exceção, prazo total por link, comparação literal da marca, horários com vírgula e colisão de nome checada antes. `tests/test_agendar.py` roda o script de verdade com as tarefas do Windows simuladas. |
| 35 | Mesma área | **REPROVADO** (3): link inicial com `\` ganhava selo (no navegador vira `/`), "à" recusado (o byte A0 do UTF-8 parecia espaço), agendador sem volta atrás se falhasse no meio; risco: diagnóstico sem prazo duro. Corrigido: todo endereço avaliado tem de ser ASCII visível sem `\`, checagem nos bytes, nome do produto só com caracteres de caminho (sem `%2F`/`%5C`), agendador com cópia XML e devolução, diagnóstico com prazo duro e conferência que pausa se a Shopee parar de responder. |
| 36 | Mesma área | **REPROVADO** (2): `Location: ///product/...` o Python juntava no host atual e o navegador lê o host `product` (selo falso); volta atrás do agendador dizia "nada mudou" mesmo quando a remoção compensatória falhava. Corrigido: só duas formas aceitas, as que os dois leem igual (absoluta limpa `https://host[:443]/...` e caminho com uma barra no começo), sem `.`/`..` (nem `%2e`) no caminho; cada passo da volta atrás é conferido e a mensagem diz o que ficou. |
| 37 | Mesma área | **RESSALVAS**, nenhum problema novo. Riscos: suíte não executada pelo auditor, compatibilidade real com a Shopee, linha presa. |
| 38 | Mesma área, com o ensaio real abaixo | **RESSALVAS**, nenhum problema novo: "o ensaio relatado reduz o risco de incompatibilidade". Falta só o link de produto da conta da afiliada. |
| 39 | "Conferir links" (novo, 20/10): links gerados à mão no painel de afiliados | **REPROVADO** (1): endereço de produto inventado com `utm_medium=affiliates&utm_source=an_1` escrito à mão ganhava ✓ e "Abre [nome]". Corrigido: só conta a marcação que a **Shopee** põe depois de redirecionar (marcação escrita no link colado = aviso); textos dizem "endereço do produto" e "nome no endereço", nunca existência nem comissão; prazo por conexão no painel. |
| 40 | Mesma área | **REPROVADO** (1): resultado salvo pela versão anterior (sem os campos novos) ainda ganhava ✓ na tela. Corrigido: `conferencia.json` tem versão e a tela só mostra a atual; o ✓ exige TODAS as provas explícitas (redirecionou, sem marcação escrita, ID `an_<dígitos>` válido); prazo TOTAL para o formulário chegar. |
| 41 | Mesma área | **REPROVADO** (1): na página que não é de produto, a frase "A Shopee pôs a marcação de afiliado" aceitava `utm_medium=affiliates` sem o ID. Corrigido: toda frase que afirma a marcação passa pela mesma prova (`_marcacao_da_shopee`), checada por um teste que cruza todas as combinações de campos; teste de envio "pingado" prova o prazo total. |
| 42 | Mesma área | **RESSALVAS**, nenhum problema novo. Riscos: suíte e teste pingado não executados pelo auditor (sem Python no ambiente dele); falta o link de produto real da conta. |

## Validação real na Shopee (19/10/2026)

Feita com o próprio código do robô (`robo/links.py`), sem a conta da afiliada:

| Endereço | O que a Shopee fez | Veredito do robô |
|---|---|---|
| link curto público de cupons (`s.shopee.com.br/…`) | 301 na forma absoluta `https://shopee.com.br/m/…` e 200 | aceito; página de campanha = sem selo |
| link curto inexistente | 301 para `https://shope.ee/error_page`, que responde 200 | quebrado (fica de fora) |
| `https://shopee.com.br/product/1/1`, item 1 | 200 | ok (selo) |
| `https://shopee.com.br/product/1/2`, item 1 | 200 | quebrado: abre outro produto |
| `https://shopee.com.br/` | 200 | sem selo |

API da Shopee (`open-api.affiliate.shopee.com.br/graphql`): com credencial falsa
respondeu o erro 10035 ("sem acesso"), o que confirma o endereço, o formato da
assinatura e a leitura dos erros.

**Ainda não validado:** produtos reais e link de afiliado de produto da conta
dela. Isso depende da liberação da Open API. O primeiro "Testar conexão" faz
essa prova: busca 3 produtos, gera 1 link de afiliado e confere se ele abre a
página do produto; só diz **TUDO CERTO** se abrir.

## Lição registrada

Para texto livre (título de vendedor), lista de **proibidos** nunca fecha: sempre
existe uma grafia nova. O que fecha é lista de **permitidos** (vocabulário) mais
uma garantia simples de verificar (nenhum número do vendedor). Os testes de
propriedade (3.000 títulos hostis aleatórios) checam essa garantia, não casos
isolados.

## Riscos aceitos (não bloqueiam)

- **Corte excessivo:** o nome publicado perde números e palavras fora do
  vocabulário. Exemplo: "Kit 6 Caixas" vira "Kit Caixas". O card mostra o
  título original para conferência.
- **Fase 1 não publica nada sozinha:** a dona do perfil revisa cada card antes de
  copiar a mensagem.
- **Suíte não executada pelo auditor:** o sandbox dele não tem Python. A suíte
  (212 testes) roda localmente antes de cada commit, travada pelo gancho
  `pre-commit`.
- **Selo dos links ≠ produto existe:** para um robô, qualquer página de produto
  da Shopee responde 200 (é um app de página única), até a de produto que não
  existe (teste real de 19/10). O selo afirma só que o link leva à página do
  produto certo; a existência quem confirma é a API, na mesma rodada.
- **Linha presa na conferência:** o prazo duro libera a rodada, mas não mata a
  linha que ficou esperando a rede. Ela é *daemon*: morre quando o processo da
  rodada termina, e cada rodada é um processo próprio (painel e Agendador
  chamam `python -m robo rodar`). Só um servidor que mande bytes devagar, sem
  parar, a mantém viva até lá; depois de 3 falhas seguidas a conferência pausa.
- **Forma de endereço estranha = quebrado:** se a Shopee um dia redirecionar com
  uma forma fora das duas aceitas, os links somem da tela em vez de ganhar selo.
  O "Testar conexão" mostra isso no passo 6, com o caminho do link.
