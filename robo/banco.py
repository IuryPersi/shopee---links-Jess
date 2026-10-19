"""Historico local de precos (SQLite). E ele que desmascara o desconto de vitrine:
a Shopee informa o % de desconto, mas so o nosso historico diz se o preco caiu mesmo."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from .shopee_api import Oferta

ESQUEMA = """
CREATE TABLE IF NOT EXISTS produtos (
    item_id      INTEGER PRIMARY KEY,
    shop_id      INTEGER,
    nome         TEXT NOT NULL,
    loja         TEXT,
    imagem       TEXT,
    link_produto TEXT,
    link_oferta  TEXT,
    cat_ids      TEXT,
    shop_type    TEXT,
    primeira_vez REAL NOT NULL,
    ultima_vez   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS observacoes (
    item_id   INTEGER NOT NULL,
    ts        REAL NOT NULL,
    preco_min REAL NOT NULL,
    preco_max REAL,
    desconto  INTEGER,
    vendas    INTEGER,
    nota      REAL,
    comissao  REAL,
    PRIMARY KEY (item_id, ts)
);
CREATE TABLE IF NOT EXISTS links (
    item_id INTEGER NOT NULL,
    sub_ids TEXT NOT NULL,
    link    TEXT NOT NULL,
    ts      REAL NOT NULL,
    PRIMARY KEY (item_id, sub_ids)
);
CREATE TABLE IF NOT EXISTS sugestoes (
    item_id INTEGER NOT NULL,
    ts      REAL NOT NULL,
    preco   REAL NOT NULL,
    tag     TEXT,
    PRIMARY KEY (item_id, ts)
);
CREATE TABLE IF NOT EXISTS execucoes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio    REAL NOT NULL,
    fim       REAL,
    chamadas  INTEGER,
    lidas     INTEGER,
    escolhidas INTEGER,
    erros     TEXT
);
"""

# Duas leituras do mesmo produto com menos que isso de distancia viram uma so
# (o mesmo item aparece em varias buscas da mesma rodada).
JANELA_MESMA_LEITURA = 30 * 60


class RodadaEmAndamento(RuntimeError):
    pass


class Trava:
    """Impede duas rodadas ao mesmo tempo (Agendador + clique manual dobrariam as chamadas)."""

    def __init__(self, caminho: Path, validade_s: float = 2 * 3600):
        self.caminho = Path(caminho)
        self.validade_s = validade_s
        self._fd = None

    def __enter__(self):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        if self.caminho.exists() and time.time() - self.caminho.stat().st_mtime > self.validade_s:
            self.caminho.unlink(missing_ok=True)  # trava velha de rodada que morreu
        try:
            self._fd = os.open(str(self.caminho), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RodadaEmAndamento(
                f"ja existe uma rodada em andamento ({self.caminho.name}); "
                "se tiver certeza que nao ha, apague esse arquivo") from None
        os.write(self._fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *_):
        if self._fd is not None:
            os.close(self._fd)
        self.caminho.unlink(missing_ok=True)


class Banco:
    def __init__(self, caminho: str | Path):
        em_memoria = str(caminho) == ":memory:"
        if not em_memoria:
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(caminho), timeout=30)
        if not em_memoria:
            self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(ESQUEMA)
        self.con.commit()

    def fechar(self):
        self.con.close()

    def registrar(self, o: Oferta, ts: float | None = None, commit: bool = True) -> bool:
        """Grava produto + observacao de preco. Retorna False se ja havia leitura recente."""
        ts = time.time() if ts is None else ts
        cur = self.con.cursor()
        cur.execute(
            """INSERT INTO produtos (item_id, shop_id, nome, loja, imagem, link_produto, link_oferta,
                                     cat_ids, shop_type, primeira_vez, ultima_vez)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(item_id) DO UPDATE SET
                 shop_id=excluded.shop_id, nome=excluded.nome, loja=excluded.loja,
                 imagem=excluded.imagem, link_produto=excluded.link_produto,
                 link_oferta=excluded.link_oferta, cat_ids=excluded.cat_ids,
                 shop_type=excluded.shop_type, ultima_vez=excluded.ultima_vez""",
            (o.item_id, o.shop_id, o.nome, o.loja, o.imagem, o.link_produto, o.link_oferta,
             json.dumps(o.cat_ids), json.dumps(o.shop_type), ts, ts),
        )
        recente = cur.execute(
            "SELECT ts FROM observacoes WHERE item_id=? AND ts>? AND ts<=? ORDER BY ts DESC LIMIT 1",
            (o.item_id, ts - JANELA_MESMA_LEITURA, ts + JANELA_MESMA_LEITURA),
        ).fetchone()
        novo = not recente
        if novo:
            cur.execute(
                "INSERT OR REPLACE INTO observacoes VALUES (?,?,?,?,?,?,?,?)",
                (o.item_id, ts, o.preco_min, o.preco_max, o.desconto, o.vendas, o.nota, o.comissao),
            )
        else:
            # mesma janela de leitura: guarda o MENOR preco visto (nunca infla a referencia
            # futura nem apaga um minimo que o robo ja observou) e o resto da mais nova
            cur.execute(
                """UPDATE observacoes SET preco_min=MIN(preco_min, ?), preco_max=MIN(COALESCE(preco_max, ?), ?),
                          desconto=?, vendas=?, nota=?, comissao=?
                   WHERE item_id=? AND ts=?""",
                (o.preco_min, o.preco_max, o.preco_max, o.desconto, o.vendas, o.nota, o.comissao,
                 o.item_id, recente[0]),
            )
        if commit:
            self.con.commit()
        return novo

    def commit(self):
        self.con.commit()

    def historico(self, item_id: int, desde: float, ate: float | None = None) -> list[tuple[float, float, float]]:
        """[(ts, preco_min, preco_max)] em ordem cronologica."""
        sql = "SELECT ts, preco_min, COALESCE(preco_max, preco_min) FROM observacoes WHERE item_id=? AND ts>=?"
        args: list = [item_id, desde]
        if ate is not None:
            sql += " AND ts<?"
            args.append(ate)
        return [(float(t), float(p), float(m)) for t, p, m in self.con.execute(sql + " ORDER BY ts", args)]

    def link_salvo(self, item_id: int, sub_ids: list[str], validade: float, agora: float | None = None) -> str | None:
        agora = time.time() if agora is None else agora
        linha = self.con.execute(
            "SELECT link, ts FROM links WHERE item_id=? AND sub_ids=?",
            (item_id, json.dumps(sub_ids)),
        ).fetchone()
        if linha and agora - linha[1] < validade:
            return linha[0]
        return None

    def salvar_link(self, item_id: int, sub_ids: list[str], link: str, ts: float | None = None):
        self.con.execute(
            "INSERT OR REPLACE INTO links VALUES (?,?,?,?)",
            (item_id, json.dumps(sub_ids), link, time.time() if ts is None else ts),
        )
        self.con.commit()

    def ultima_sugestao(self, item_id: int, antes_de: float) -> tuple[float, float] | None:
        """(ts, preco) da ultima vez que o item foi para a vitrine."""
        linha = self.con.execute(
            "SELECT ts, preco FROM sugestoes WHERE item_id=? AND ts<? ORDER BY ts DESC LIMIT 1",
            (item_id, antes_de),
        ).fetchone()
        return (float(linha[0]), float(linha[1])) if linha else None

    def registrar_sugestao(self, item_id: int, ts: float, preco: float, tag: str):
        self.con.execute("INSERT OR REPLACE INTO sugestoes VALUES (?,?,?,?)", (item_id, ts, preco, tag))

    def limpar_antigos(self, antes_de: float) -> int:
        cur = self.con.execute("DELETE FROM observacoes WHERE ts<?", (antes_de,))
        self.con.execute("DELETE FROM links WHERE ts<?", (antes_de,))
        self.con.commit()
        return cur.rowcount

    def abrir_execucao(self, inicio: float) -> int:
        cur = self.con.execute("INSERT INTO execucoes (inicio) VALUES (?)", (inicio,))
        self.con.commit()
        return int(cur.lastrowid)

    def fechar_execucao(self, id_: int, fim: float, chamadas: int, lidas: int,
                        escolhidas: int, erros: list[str]):
        self.con.execute(
            "UPDATE execucoes SET fim=?, chamadas=?, lidas=?, escolhidas=?, erros=? WHERE id=?",
            (fim, chamadas, lidas, escolhidas, json.dumps(erros, ensure_ascii=False), id_),
        )
        self.con.commit()

    def resumo(self) -> dict:
        c = self.con
        return {
            "produtos": c.execute("SELECT COUNT(*) FROM produtos").fetchone()[0],
            "observacoes": c.execute("SELECT COUNT(*) FROM observacoes").fetchone()[0],
            "execucoes": c.execute("SELECT COUNT(*) FROM execucoes").fetchone()[0],
            "primeira": c.execute("SELECT MIN(ts) FROM observacoes").fetchone()[0],
        }
