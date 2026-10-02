"""Armazenamento dos dados do condomínio em SQLite.

A exclusividade de reserva (Garantia 5) não é checada em Python: ela é um
índice único parcial no próprio banco. Duas gravações simultâneas para a mesma
área e data fazem o SQLite recusar a segunda no instante do INSERT, mesmo que
as duas tenham conferido a agenda antes e a tenham visto livre.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS reservas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo TEXT NOT NULL UNIQUE,
  apartamento TEXT NOT NULL,
  area TEXT NOT NULL,
  data TEXT NOT NULL,
  taxa REAL NOT NULL,
  cancelada_em TEXT
);
-- A garantia de "uma reserva ativa por área e data" mora aqui.
CREATE UNIQUE INDEX IF NOT EXISTS reserva_ativa_unica
  ON reservas(area, data) WHERE cancelada_em IS NULL;
CREATE TABLE IF NOT EXISTS visitantes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  apartamento TEXT NOT NULL,
  nome TEXT NOT NULL,
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sequencia (
  nome TEXT PRIMARY KEY,
  valor INTEGER NOT NULL
);
"""


@asynccontextmanager
async def _conexao():
    con = await aiosqlite.connect(config.BANCO_CONDOMINIO)
    con.row_factory = aiosqlite.Row
    await con.execute("PRAGMA journal_mode=WAL")
    await con.execute("PRAGMA busy_timeout=10000")
    try:
        yield con
    finally:
        await con.close()


def _ler_json(nome: str) -> list[dict[str, Any]]:
    return json.loads((config.DADOS / nome).read_text(encoding="utf-8"))


async def inicializar() -> None:
    """Cria o esquema e, num banco novo, carrega o estado inicial de dados/."""
    config.ESTADO.mkdir(parents=True, exist_ok=True)
    async with _conexao() as con:
        await con.executescript(ESQUEMA)
        await con.commit()
        cur = await con.execute("SELECT COUNT(*) AS n FROM reservas")
        vazio = (await cur.fetchone())["n"] == 0
    if vazio:
        await restaurar()


async def restaurar() -> None:
    """Volta reservas e visitantes ao estado de dados/ e reinicia a sequência."""
    config.ESTADO.mkdir(parents=True, exist_ok=True)
    async with _conexao() as con:
        await con.executescript(ESQUEMA)
        await con.execute("DELETE FROM reservas")
        await con.execute("DELETE FROM visitantes")
        for r in _ler_json("reservas.json"):
            await con.execute(
                "INSERT INTO reservas (codigo, apartamento, area, data, taxa)"
                " VALUES (?, ?, ?, ?, ?)",
                (r["codigo"], r["apartamento"], r["area"], r["data"], _taxa(r["area"])),
            )
        for v in _ler_json("visitantes.json"):
            await con.execute(
                "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
                (v["apartamento"], v["nome"], v["data"]),
            )
        await con.execute(
            "INSERT INTO sequencia (nome, valor) VALUES ('reserva_codigo', ?)"
            " ON CONFLICT(nome) DO UPDATE SET valor = excluded.valor",
            (config.INICIO_CODIGO_RESERVA,),
        )
        await con.commit()


def _areas() -> dict[str, dict[str, Any]]:
    return {a["id"]: a for a in _ler_json("areas.json")}


def _taxa(area: str) -> float:
    return float(_areas().get(area, {}).get("taxa", 0.0))


def areas() -> list[dict[str, Any]]:
    return _ler_json("areas.json")


def area_existe(area: str) -> bool:
    return area in _areas()


def taxa_da_area(area: str) -> float:
    return _taxa(area)


async def reservas_ativas(apartamento: str) -> list[dict[str, Any]]:
    async with _conexao() as con:
        cur = await con.execute(
            "SELECT codigo, area, data FROM reservas"
            " WHERE apartamento = ? AND cancelada_em IS NULL"
            " ORDER BY data, codigo",
            (apartamento,),
        )
        return [dict(linha) for linha in await cur.fetchall()]


async def visitantes(apartamento: str) -> list[dict[str, Any]]:
    async with _conexao() as con:
        cur = await con.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, nome",
            (apartamento,),
        )
        return [dict(linha) for linha in await cur.fetchall()]


async def data_ocupada(area: str, data: str) -> bool:
    """Diz se a área tem reserva ativa na data. Nunca revela de quem é."""
    async with _conexao() as con:
        cur = await con.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ?"
            " AND cancelada_em IS NULL LIMIT 1",
            (area, data),
        )
        return await cur.fetchone() is not None


async def criar_reserva(
    apartamento: str, area: str, data: str
) -> dict[str, Any] | None:
    """Grava a reserva. Devolve None se a área já estiver reservada nessa data."""
    taxa = _taxa(area)
    async with _conexao() as con:
        try:
            await con.execute("BEGIN IMMEDIATE")
            cur = await con.execute(
                "SELECT valor FROM sequencia WHERE nome = 'reserva_codigo'"
            )
            linha = await cur.fetchone()
            codigo = f"RSV-{linha['valor']}"
            await con.execute(
                "UPDATE sequencia SET valor = valor + 1 WHERE nome = 'reserva_codigo'"
            )
            await con.execute(
                "INSERT INTO reservas (codigo, apartamento, area, data, taxa)"
                " VALUES (?, ?, ?, ?, ?)",
                (codigo, apartamento, area, data, taxa),
            )
        except sqlite3.IntegrityError:
            await con.rollback()
            return None
        except Exception:
            await con.rollback()
            raise
        await con.commit()
    return {"codigo": codigo, "area": area, "data": data, "taxa": taxa}


async def cancelar_reserva(
    apartamento: str,
    *,
    codigo: str | None = None,
    area: str | None = None,
    data: str | None = None,
) -> str | None:
    """Cancela uma reserva ativa do apartamento. Devolve o código cancelado.

    O `apartamento` entra sempre no WHERE: é o que impede que a sessão de um
    morador cancele ou descubra a reserva de outro.
    """
    if not codigo and not (area and data):
        return None
    condicoes = ["apartamento = ?", "cancelada_em IS NULL"]
    valores: list[Any] = [apartamento]
    if codigo:
        condicoes.append("codigo = ?")
        valores.append(codigo)
    if area:
        condicoes.append("area = ?")
        valores.append(area)
    if data:
        condicoes.append("data = ?")
        valores.append(data)

    async with _conexao() as con:
        await con.execute("BEGIN IMMEDIATE")
        cur = await con.execute(
            f"SELECT codigo FROM reservas WHERE {' AND '.join(condicoes)} LIMIT 1",
            valores,
        )
        linha = await cur.fetchone()
        if linha is None:
            await con.rollback()
            return None
        await con.execute(
            "UPDATE reservas SET cancelada_em = datetime('now') WHERE codigo = ?",
            (linha["codigo"],),
        )
        await con.commit()
    return linha["codigo"]


async def autorizar_visitante(
    apartamento: str, nome: str, data: str
) -> dict[str, Any]:
    async with _conexao() as con:
        await con.execute(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
        await con.commit()
    return {"nome": nome, "data": data}
