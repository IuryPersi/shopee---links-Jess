"""Uso:
    python -m robo rodar        coleta de verdade (precisa do .env) e gera a vitrine
    python -m robo diagnostico  testa credencial, campos da API e geracao de link (2-3 chamadas)
    python -m robo demo         vitrine com produtos FICTICIOS, sem internet
    python -m robo resumo       tamanho do historico de precos
    python -m robo conferir LINK [LINK...]   confere links gerados a mao no painel de afiliados
                                (para onde levam, produto, marcacao de afiliado); sem API, sem .env
    python -m robo postagem --link L --preco P [--nome N] [--tag T]   monta a mensagem de um
                                produto achado a mao (link conferido + NBCAL); sem API, sem .env
"""
from __future__ import annotations

import copy
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .banco import Banco, RodadaEmAndamento, Trava
from .config import RAIZ, ler_env, ler_nicho
from .shopee_api import CAMPOS_OFERTA, ClienteShopee, ErroShopee

PASTA_DADOS = RAIZ / "dados"
PASTA_SAIDA = RAIZ / "saida"


def _log_arquivo(msg: str):
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    with (PASTA_SAIDA / "robo.log").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def log(msg: str):
    print(msg, flush=True)
    _log_arquivo(msg)


def _cliente(cfg: dict) -> ClienteShopee:
    env = ler_env()
    faltam = [k for k in ("SHOPEE_APP_ID", "SHOPEE_SECRET") if not env.get(k)]
    if faltam:
        raise SystemExit(
            "Faltam credenciais no arquivo .env: " + ", ".join(faltam) +
            "\nPegue em affiliate.shopee.com.br > Open API (App ID e Secret) e copie .env.exemplo para .env.")
    return ClienteShopee(env["SHOPEE_APP_ID"], env["SHOPEE_SECRET"],
                         intervalo=float(cfg["coleta"].get("intervalo_entre_chamadas_s", 1.2)))


def cmd_rodar() -> int:
    """Saida: 0 ok | 2 conta/credencial | 3 coleta quebrou (vitrine anterior mantida) |
    4 ja rodando | 5 saida/ultima incompleta (arquivo aberto) - a pasta datada esta completa."""
    from .links import verificador_com_pausa
    from .pipeline import ErroColeta, rodar
    cfg = ler_nicho()
    cliente = _cliente(cfg)
    # cada link e aberto (sem baixar a pagina) para conferir que leva ao produto certo
    verificador = verificador_com_pausa() if cfg["coleta"].get("conferir_links", True) else None
    inicio = time.time()
    try:
        with Trava(PASTA_DADOS / "rodando.lock"):
            banco = Banco(PASTA_DADOS / "robo.db")
            try:
                res = rodar(cliente, banco, cfg, PASTA_SAIDA, log=log, verificador=verificador)
            finally:
                banco.fechar()
    except RodadaEmAndamento as e:
        log(f"NAO RODEI: {e}")
        return 4
    except ErroShopee as e:
        log(f"PAROU (conta/credencial): {e}")
        return 2
    except ErroColeta as e:
        log(f"PAROU (coleta): {e}. A vitrine anterior foi mantida.")
        return 3
    log(f"Pronto em {time.time() - inicio:.0f}s: {res.lidas} lidas, {res.total_escolhidos} escolhidas, "
        f"{res.chamadas} chamadas, {len(res.erros)} erros, {len(res.avisos)} avisos.")
    if res.links_sem_conferencia:
        log(f"Aviso: {res.links_sem_conferencia} link(s) foram para a tela SEM o selo: a Shopee nao "
            f"respondeu na conferencia.")
    if res.saida_parcial:
        pasta = next(iter(res.arquivos.values())).parent
        log(f"ATENCAO: saida/ultima ficou INCOMPLETA (arquivo aberto?). Use a pasta completa: {pasta}")
        return 5
    log(f"Vitrine: {PASTA_SAIDA / 'ultima' / 'vitrine.html'}")
    return 0


def cmd_diagnostico() -> int:
    """Lista de verificacao do primeiro uso real: credencial, acesso, campos, link, link abrindo.
    Gasta 2-3 chamadas da API e abre 1 link."""
    from .links import conferir_com_prazo
    cfg = ler_nicho()

    def passo(n, texto, situacao):
        print(f"[{n}] {texto:<34} {situacao}", flush=True)

    cliente = _cliente(cfg)
    passo(1, "Credenciais no .env", f"OK (App ID {cliente.app_id[:3]}***)")
    passo(2, "Relogio do PC", f"{datetime.now():%d/%m/%Y %H:%M:%S} (a assinatura usa a hora certa)")
    try:
        ofertas, _ = cliente.buscar_ofertas(keyword="organizador", limit=3)
    except ErroShopee as e:
        passo(3, "Conexao e acesso a Open API", f"FALHOU: {e}")
        if e.codigo == 11001:
            try:
                cliente.buscar_ofertas(keyword="organizador", limit=1,
                                       campos="itemId productName priceMin offerLink productLink")
                print("    Com campos minimos funciona: algum campo pedido nao existe nesta versao da API.")
                print(f"    Campos pedidos: {CAMPOS_OFERTA}")
            except ErroShopee as e2:
                print(f"    Com campos minimos tambem falhou: {e2}")
        print("RESULTADO: ainda NAO esta pronto. Veja o passo que falhou acima.")
        return 2
    passo(3, "Conexao e acesso a Open API", "OK")
    if not ofertas:
        passo(4, "Busca de produtos", "ATENCAO: a busca voltou vazia")
        print("RESULTADO: conexao OK, mas a busca nao trouxe produtos. Me mande esta saida.")
        return 2
    faltando = sorted({campo for o in ofertas for campo, vazio in (
        ("nota", o.nota is None), ("comissao", o.comissao is None), ("foto", not o.imagem),
        ("link do produto", not o.link_produto), ("offerLink", not o.link_oferta)) if vazio})
    passo(4, "Busca de produtos (campos)",
          f"OK: {len(ofertas)} ofertas" + (f" (sem: {', '.join(faltando)})" if faltando else ""))
    for o in ofertas:
        comissao = "?" if o.comissao is None else f"{o.comissao * 100:.1f}%".replace(".", ",")
        print(f"    - {o.nome[:55]} | R$ {o.preco_min:.2f} | -{o.desconto}% | nota {o.nota} | "
              f"{o.vendas} vendas | comissao {comissao} | shopType={o.shop_type}")
    alvo = next((o for o in ofertas if o.link_produto), None)
    if alvo is None:
        print("RESULTADO: a API nao mandou o link do produto. Me mande esta saida.")
        return 2
    try:
        link = cliente.link_curto(alvo.link_produto, ["diagnostico"])
    except ErroShopee as e:
        passo(5, "Geracao do link de afiliado", f"FALHOU: {e}")
        print("RESULTADO: a busca funciona, mas o link de afiliado nao. Me mande esta saida.")
        return 2
    passo(5, "Geracao do link de afiliado", f"OK: {link}")
    trilha: list[str] = []
    estado, detalhe = conferir_com_prazo(link, alvo.item_id, trilha=trilha)  # prazo duro (35a rodada)
    textos = {"ok": "OK: leva a pagina do produto certo",
              "ok_sem_id": f"abre na Shopee, mas a pagina final nao e a do produto ({detalhe})",
              "quebrado": f"FALHOU: {detalhe}", "sem_resposta": f"nao deu para conferir agora ({detalhe})"}
    passo(6, "O link abre o produto?", textos.get(estado, estado))
    for salto in trilha:  # o caminho do link, sem os parametros de rastreio: ajuda se algo falhar
        print(f"    -> {salto}")
    print(f"Chamadas usadas: {cliente.chamadas}.")
    if estado == "quebrado":
        print("RESULTADO: o link gerado nao abre o produto. Me mande esta saida.")
        return 2
    if estado != "ok":  # 33a rodada: so 'TUDO CERTO' quando o link abriu o produto CERTO
        print("RESULTADO: conexao e geracao de link OK, mas nao deu para confirmar que o link abre o "
              "produto certo agora. Rode o teste de novo em alguns minutos; se repetir, me mande esta saida.")
        return 1
    print("RESULTADO: TUDO CERTO. Pode usar 'Atualizar achados' na tela.")
    return 0


def cmd_demo() -> int:
    from .demo import BUSCAS_DEMO, ClienteDemo, semear_historico
    from .pipeline import rodar
    cfg = copy.deepcopy(ler_nicho())
    for tag, t in cfg["tags"].items():
        t["buscas"] = BUSCAS_DEMO.get(tag, [])
    banco = Banco(":memory:")
    agora = time.time()
    semear_historico(banco, agora)
    res = rodar(ClienteDemo(), banco, cfg, PASTA_SAIDA / "demo", agora=agora, log=print)
    banco.fechar()
    print(f"Demo: {res.total_escolhidos} escolhidas de {res.lidas}. Recusas: {dict(res.recusados)}")
    print(f"Abra: {PASTA_SAIDA / 'demo' / 'ultima' / 'vitrine.html'}")
    return 0


def cmd_conferir(argv: list[str], abrir=None, pausa: float = 0.4) -> int:
    """Confere links colados a mao. Nao usa a API nem o .env. Grava saida/conferencia.json, que a
    tela "Conferir links" do painel mostra. Saida: 0 conferiu | 1 nenhum link no que foi colado."""
    import json
    from .links import (ICONES, MAX_LINKS_COLADOS, VERSAO_CONFERENCIA, examinar_link, links_do_texto,
                        nivel_do_exame, texto_do_exame)
    texto = " ".join(argv) if argv else sys.stdin.read()
    links = links_do_texto(texto)
    if not links:
        print("Nenhum link para conferir. Uso: python -m robo conferir https://s.shopee.com.br/...")
        return 1
    print(f"Conferindo {len(links)} link(s) na Shopee (no maximo {MAX_LINKS_COLADOS} por vez)...", flush=True)
    resultados, seguidos = [], 0
    for i, link in enumerate(links, 1):
        if seguidos >= 3:  # a Shopee parou de responder: nao insiste link a link
            r = {"link": link, "estado": "sem_resposta", "trilha": [], "destino": None, "loja": None,
                 "item": None, "nome": None, "afiliado": None, "redirecionou": False, "marca_escrita": False,
                 "detalhe": "conferencia pausada: a Shopee parou de responder"}
        else:
            r = examinar_link(link, abrir=abrir)
            seguidos = seguidos + 1 if r["estado"] == "sem_resposta" else 0
            if i < len(links):
                time.sleep(pausa)
        resultados.append(r)
        print(f"[{i}] {link}\n    {ICONES[nivel_do_exame(r)]} {texto_do_exame(r)}", flush=True)
        if r["trilha"]:
            print("    caminho: " + " -> ".join(r["trilha"]), flush=True)
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    destino = PASTA_SAIDA / "conferencia.json"
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(json.dumps({"versao": VERSAO_CONFERENCIA,
                                      "quando": datetime.now().isoformat(timespec="seconds"),
                                      "resultados": resultados}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    os.replace(temporario, destino)  # o painel nunca le um arquivo pela metade
    certos = sum(nivel_do_exame(r) == "ok" for r in resultados)
    print(f"Pronto: em {certos} de {len(resultados)} a Shopee leva ao endereco de um produto e poe a marcacao "
          f"de afiliado (se o produto existe, so abrindo). Detalhes na tela 'Conferir links' e em {destino}.")
    return 0


def _argumentos(argv: list[str], nomes: tuple[str, ...]) -> dict | None:
    """--chave valor (cada chave no maximo uma vez). None se vier algo fora disso."""
    vals: dict = {}
    i = 0
    while i < len(argv):
        chave = argv[i]
        if not chave.startswith("--") or chave[2:] not in nomes or chave[2:] in vals or i + 1 >= len(argv):
            return None
        vals[chave[2:]] = argv[i + 1]
        i += 2
    return vals


def cmd_postagem(argv: list[str], abrir=None) -> int:
    """python -m robo postagem --link L --preco P [--nome N] [--tag T]
    Monta a mensagem de um produto achado a mao (sem API). Grava saida/postagens.json (as ultimas
    20) para a tela 'Montar postagem'. Saida: 0 mensagem pronta | 1 nao montou (motivo na tela)."""
    import json
    from .postagem import MAX_POSTAGENS, VERSAO_POSTAGEM, assinatura, montar_postagem
    args = _argumentos(argv, ("link", "preco", "nome", "tag"))
    if not args or not args.get("link") or "preco" not in args:
        print("Uso: python -m robo postagem --link https://s.shopee.com.br/... --preco 29,90 [--nome NOME] [--tag maternidade]")
        return 1
    r = montar_postagem(args["link"].strip(), args["preco"], ler_nicho(), nome_digitado=args.get("nome", ""),
                        tag=args.get("tag", "maternidade"), abrir=abrir)
    r["quando"] = datetime.now().isoformat(timespec="seconds")
    if r["ok"]:
        r["assinatura"] = assinatura(r)  # so a tela com a chave local aceita como pronta
    destino = PASTA_SAIDA / "postagens.json"
    try:
        antigas = json.loads(destino.read_text(encoding="utf-8"))
        lista = antigas.get("postagens", []) if antigas.get("versao") == VERSAO_POSTAGEM else []
    except (OSError, ValueError, AttributeError):
        lista = []
    lista = [r] + [p for p in lista if isinstance(p, dict)][: MAX_POSTAGENS - 1]
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(json.dumps({"versao": VERSAO_POSTAGEM, "postagens": lista}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    os.replace(temporario, destino)
    if r["ok"]:
        print("MENSAGEM PRONTA:\n" + r["mensagem"])
        for aviso in r["avisos"]:
            print(f"ATENCAO: {aviso}")
        return 0
    print("NAO MONTEI A MENSAGEM:")
    for motivo in r["motivos"]:
        print(f"  - {motivo}")
    return 1


def cmd_resumo() -> int:
    caminho = PASTA_DADOS / "robo.db"
    if not caminho.exists():
        print("Ainda nao ha historico (rode 'python -m robo rodar').")
        return 0
    banco = Banco(caminho)
    r = banco.resumo()
    banco.fechar()
    desde = datetime.fromtimestamp(r["primeira"]).strftime("%d/%m/%Y") if r["primeira"] else "-"
    print(f"{r['produtos']} produtos, {r['observacoes']} leituras de preco desde {desde}, {r['execucoes']} rodadas.")
    return 0


def main(argv: list[str]) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")  # emoji no console do Windows
        except (AttributeError, ValueError):
            pass
    os.chdir(RAIZ)
    cmd = argv[0] if argv else "rodar"
    if cmd == "conferir":
        return cmd_conferir(argv[1:])
    if cmd == "postagem":
        return cmd_postagem(argv[1:])
    comandos = {"rodar": cmd_rodar, "diagnostico": cmd_diagnostico, "demo": cmd_demo, "resumo": cmd_resumo}
    if cmd not in comandos:
        print(__doc__)
        return 1
    return comandos[cmd]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
