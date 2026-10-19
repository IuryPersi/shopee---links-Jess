"""Carrega o .env (credenciais) e o config/nicho.json (regras do nicho)."""
from __future__ import annotations

import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

OBRIGATORIAS = {
    "filtros": ["desconto_minimo", "nota_minima", "vendas_minimas", "preco_minimo",
                "preco_maximo", "max_por_tag", "max_por_loja_por_tag"],
    "coleta": ["paginas_por_termo", "itens_por_pagina", "ordenacoes"],
}


def ler_env(caminho: Path | None = None) -> dict[str, str]:
    """KEY=VALOR simples; variavel de ambiente ja definida tem prioridade."""
    caminho = caminho or RAIZ / ".env"
    valores: dict[str, str] = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            valores[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SHOPEE_APP_ID", "SHOPEE_SECRET"):
        if os.environ.get(k):
            valores[k] = os.environ[k]
    return valores


def ler_nicho(caminho: Path | None = None) -> dict:
    caminho = caminho or RAIZ / "config" / "nicho.json"
    cfg = json.loads(caminho.read_text(encoding="utf-8-sig"))  # Bloco de Notas salva com BOM
    for secao, chaves in OBRIGATORIAS.items():
        faltam = [k for k in chaves if k not in cfg.get(secao, {})]
        if faltam:
            raise ValueError(f"config/nicho.json: faltam {secao}.{', '.join(faltam)}")
    if not cfg.get("tags"):
        raise ValueError("config/nicho.json: nenhuma tag configurada")
    from .texto import registrar_vocabulario, registrar_vocabulario_legenda, validar_textos_do_config
    validar_textos_do_config(cfg)
    palavras = [p for t in cfg["tags"].values() for p in t.get("palavras", [])]
    registrar_vocabulario(palavras, recomecar=True)
    registrar_vocabulario_legenda(palavras, recomecar=True)
    for tag, t in cfg["tags"].items():
        if not t.get("buscas"):
            raise ValueError(f"config/nicho.json: tag '{tag}' sem termos de busca")
    return cfg
