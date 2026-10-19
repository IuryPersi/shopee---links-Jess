"""Uso:
    python -m robo rodar        coleta de verdade (precisa do .env) e gera a vitrine
    python -m robo diagnostico  testa credencial, campos da API e geracao de link (2-3 chamadas)
    python -m robo demo         vitrine com produtos FICTICIOS, sem internet
    python -m robo resumo       tamanho do historico de precos
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
    comandos = {"rodar": cmd_rodar, "diagnostico": cmd_diagnostico, "demo": cmd_demo, "resumo": cmd_resumo}
    if cmd not in comandos:
        print(__doc__)
        return 1
    return comandos[cmd]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
