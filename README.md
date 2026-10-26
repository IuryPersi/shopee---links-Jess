# Robô de Achadinhos Shopee

Acha as melhores ofertas da Shopee nas tags do perfil (casa, maternidade, bebê,
feminino, cozinha, limpeza), **desmascara desconto falso** e entrega cada produto
com a mensagem pronta para colar: nome, **De R$ X por R$ Y**, nota, vendidos e o
link de afiliado.

## Uso do dia a dia

1. Dois cliques em `PAINEL.bat`. O navegador abre sozinho em
   **http://127.0.0.1:8031**, a tela **Achadinhos de hoje**, assim que o
   painel estiver no ar. Uma janela preta fica aberta: **é o painel**. Deixe
   essa janela aberta enquanto usa, porque fechá-la desliga o painel. Se clicar
   de novo com ele aberto, só abre a tela, sem erro.
2. Clique em **Atualizar achados** e espere uns minutos.
3. Em cada card, **Copiar mensagem** e cole no WhatsApp, story ou Telegram.
   **Link** copia só o link; **Feed** copia a versão sem link, para o feed.

A mensagem sai assim:

```
#publi · link de afiliado
🍳 Jogo de Espátulas de Silicone Antiaderente
De R$ 74,90 por R$ 42,90 (-43%)
⭐ 4,9 · 9,8 mil vendidos
👉 https://s.shopee.com.br/…
Preço pode mudar a qualquer momento.
```

O painel só funciona neste computador (não aparece na rede) e só aceita pedidos
vindos dele mesmo. Ao postar no Instagram, marque **"parceria paga"**.

**Os links são conferidos:** antes de ir para a tela, cada link de afiliado é
aberto, sem baixar a página, e seguido até a página onde a pessoa chega. Fica
de fora o link que cai na página de erro da Shopee, abre **outro** produto ou
sai da Shopee. O selo **"✓ link conferido"** aparece quando a página final é a
página daquele produto (o ID exato no endereço). Sem o selo, o link abriu na
Shopee, mas não deu para confirmar o produto (por exemplo, a Shopee pediu
login ao robô). A existência do produto quem confirma é a própria API, na
mesma atualização. Se a Shopee parar de responder à conferência (3 vezes
seguidas), o robô para de conferir naquela atualização e os links seguintes
vão sem o selo; o log avisa quantos ficaram assim.

## Montar postagem (sem a Open API)

Para postar enquanto a Open API não é liberada:

1. Ache a promoção na Shopee (Ofertas Relâmpago, Mãe e Bebê, mais vendidos).
2. Gere o link no [painel de afiliados](https://affiliate.shopee.com.br/) →
   **Link personalizado**.
3. Na tela, em **Montar postagem**, cole o link e o **preço que está vendo**.
   Se o endereço não trouxer o nome do produto, digite o nome também. Escolha a
   tag (já vem em maternidade) e clique em **Montar postagem**.
4. O robô:
   - confere o link (precisa dar ✓: endereço de produto com a marcação de
     afiliado da Shopee);
   - barra mamadeira, bico, chupeta e fórmula (NBCAL), falsificação e
     proibidos;
   - limpa o nome (sem números nem promessas do vendedor);
   - monta a mensagem com **"Por R$ Y"**.
5. **Copiar mensagem** (ou **Feed**) e poste. Confira o preço no app antes.

O "De R$ X" não aparece aqui: ele só sai quando o histórico do robô comprova a
queda, e isso depende da Open API.

Pelo terminal:
`py -3.12 -m robo postagem --link https://s.shopee.com.br/… --preco 29,90 [--nome …] [--tag maternidade]`.

## Conferir links gerados à mão

Serve enquanto a Open API não é liberada, ou para conferir um link antes de
postar. Não usa a API nem o `.env`.

1. No [painel de afiliados](https://affiliate.shopee.com.br/), gere o link em
   **Link personalizado**.
2. Na tela, abra **Conferir links**, cole os links (até 20, um por linha) e
   clique em **Conferir links**.
3. Para cada link, o robô abre na Shopee e mostra um destes resultados:
   - **✓** a Shopee leva o link ao endereço de um produto e põe a **marcação de
     afiliado** no caminho (`an_…`, o ID de afiliado). O robô mostra o ID e o
     nome que estão no endereço;
   - **⚠** abre, mas falta algo. Pode ser endereço de produto **sem** a
     marcação de afiliado (link direto do produto não é link de afiliado),
     marcação escrita à mão no próprio link, ou página que não é de produto;
   - **✗** não abre: link inexistente, expirado ou fora da Shopee;
   - **…** a Shopee não respondeu agora.

**O que a conferência não prova:** se o produto existe e está à venda. Para um
robô, a Shopee responde a qualquer endereço de produto, até de produto que não
existe. Toque em **Abrir** para ver. Ela também não prova a comissão: a
marcação mostra para qual ID de afiliado o link aponta, mas cliques e pedidos
só o relatório do painel de afiliados mostra.

Pelo terminal: `py -3.12 -m robo conferir https://s.shopee.com.br/…`.

## Primeira vez

1. No computador, abra **https://affiliate.shopee.com.br/open_api** com a conta
   de afiliada. Se o botão laranja **"Aplicar"** aparecer, clique: a tela mostra
   o **ID** e a **senha (token)**.
   - Se o botão não aparecer, a API ainda não foi liberada para a conta. Peça
     (é grátis) no formulário
     https://help.shopee.com.br/portal/webform/bbce78695c364ba18c9cbceb74ec9091
     e aguarde o e-mail da Shopee.
2. Preencha o arquivo `.env`, que já está criado na pasta, com
   `SHOPEE_APP_ID=` (o ID) e `SHOPEE_SECRET=` (a senha/token). O `.env` nunca
   vai para o Git.
3. Na tela, abra **Mais opções** → **Testar conexão com a Shopee**. O teste é
   uma lista de verificação: credencial, acesso, campos, geração do link e o
   link abrindo o produto. Se terminar em **TUDO CERTO**, use **Atualizar
   achados**.
4. Opcional (recomendado na 1ª semana): agende 3 atualizações por dia, sem
   janela:
   `powershell -NoProfile -ExecutionPolicy Bypass -File "W:\Robo Shopee\agendar.ps1"`
   (`-Horarios 07:30,12:30,20:00` muda os horários; `-Remover` desfaz). O
   script só mexe nas tarefas que ele mesmo criou e para antes de mexer em
   qualquer coisa se já existir outra tarefa com o mesmo nome. Se falhar no
   meio, devolve as tarefas antigas como estavam.

Sem credencial, o botão gera uma **demonstração** com produtos fictícios.

## O "De" só aparece quando é verdade

Decisão do dono (17/10/2026): o **De R$ X** sai **somente** quando o histórico do
próprio robô comprova a queda. O preço "de" informado pela Shopee nunca é usado,
porque muitas lojas inflam esse valor.

- **Desconto comprovado:** o robô já acompanhou o preço e viu a queda. A mensagem
  traz De/Por e o card mostra o -%.
- **Novidades:** produto bom, mas ainda sem histórico. A mensagem traz só o preço
  de agora.

**Na primeira semana** quase tudo cai em Novidades. O detector precisa de pelo
menos 3 dias distintos de preço, espalhados por alguns dias. Atualize **umas 3
vezes por dia** nessa semana; a partir da segunda, o "De/Por" passa a dominar.

## Só produtos muito bons

Para entrar, o produto precisa de:

- queda real ≥ 30% (ou desconto anunciado ≥ 30% enquanto não há histórico);
- nota ≥ 4,8 e ≥ 500 vendidos;
- preço entre R$ 12 e R$ 300 e comissão ≥ 3%;
- no máximo 5 por tag e 2 por loja, sem produtos repetidos.

Também ficam de fora:

- **desconto de vitrine:** preço de sempre, gangorra, "subiu antes de baixar",
  variação-isca;
- **NBCAL** (mamadeira, bico, chupeta, fórmula/leite infantil, papinha),
  falsificação e produtos proibidos;
- o que já foi sugerido nos últimos 5 dias, salvo se o preço cair mais 5%
  (selo **BAIXOU DE NOVO**).

Antes de gerar o link, o robô reconfere o preço na Shopee.

## O nome do produto na mensagem

O título do vendedor vem cheio de "70% OFF", "frete grátis" e números. O nome
na mensagem usa **só palavras de um vocabulário do robô** (`robo/vocabulario.py`:
produtos, materiais, cores, características) e as palavras das tags. Número,
moeda e promessa do vendedor nunca entram. O card mostra o título original
completo, para conferência.

## Por linha de comando (opcional)

```
py -3.12 -m robo rodar        # atualiza com a conta (o mesmo que o botão)
py -3.12 -m robo diagnostico  # testa a conexão
py -3.12 -m robo demo         # demonstração com produtos fictícios
py -3.12 -m robo conferir LINK [LINK...]  # confere links gerados à mão (sem API)
```

Saídas em `saida/ultima/`: `achados.json`, `mensagens.txt`, `vitrine.html`,
`ofertas.csv`.

| Código de saída | O que aconteceu |
|---|---|
| 0 | tudo certo |
| 2 | problema de conta ou credencial (a mensagem diz qual) |
| 3 | a coleta falhou (rede ou Shopee fora); os achados anteriores foram mantidos |
| 4 | já havia outra atualização em andamento |
| 5 | `saida/ultima` ficou incompleta (arquivo aberto); a pasta datada está completa |

Detalhes em `saida/robo.log`.

## Ajustar o nicho

Tudo em `config/nicho.json`: termos de busca, palavras de cada tag, exclusões,
filtros e bloqueios.

## Testes e auditoria

```
py -3.12 -m unittest discover -s tests
```

Os 233 testes rodam sem internet. No computador de desenvolvimento, um gancho
`pre-commit` roda a suíte e barra commit com teste falhando. O histórico da auditoria externa
(Codex), a validação real na Shopee e os riscos aceitos estão em
[`docs/AUDITORIA.md`](docs/AUDITORIA.md).
