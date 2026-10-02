"""Self-check do armazenamento: restauração, códigos e exclusividade.

Roda com `uv run pytest tests/` ou `uv run python -m pytest tests/`.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from residencial_aurora import armazenamento
from residencial_aurora import config


@pytest.fixture()
def banco_isolado(monkeypatch, tmp_path: Path):
    config.ESTADO.mkdir(parents=True, exist_ok=True)  # garante dir default
    monkeypatch.setattr(config, "ESTADO", tmp_path)
    monkeypatch.setattr(config, "BANCO_CONDOMINIO", tmp_path / "teste.db")
    asyncio.run(armazenamento.restaurar())
    yield


def test_restauracao_carrega_estado_inicial(banco_isolado):
    reservas = asyncio.run(armazenamento.reservas_ativas("101"))
    assert reservas == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]
    visitantes = asyncio.run(armazenamento.visitantes("302"))
    assert visitantes == [{"nome": "Marina Duarte", "data": "2030-03-16"}]


def test_codigos_novos_nao_repetem(banco_isolado):
    r1 = asyncio.run(armazenamento.criar_reserva("101", "salao-de-festas", "2030-04-20"))
    r2 = asyncio.run(armazenamento.criar_reserva("101", "salao-de-festas", "2030-04-21"))
    assert r1 is not None and r2 is not None
    assert r1["codigo"] != r2["codigo"]
    assert r1["codigo"] not in {"RSV-1377", "RSV-4821", "RSV-2950"}
    # Cancelada nunca libera o código.
    asyncio.run(armazenamento.cancelar_reserva("101", codigo=r1["codigo"]))
    r3 = asyncio.run(armazenamento.criar_reserva("101", "salao-de-festas", "2030-04-22"))
    assert r3["codigo"] != r1["codigo"]


def test_cancelamento_so_do_proprio_apartamento(banco_isolado):
    # A reserva do 302 não pode ser cancelada pela sessão do 101.
    assert asyncio.run(
        armazenamento.cancelar_reserva("101", area="salao-de-festas", data="2030-03-16")
    ) is None
    assert len(asyncio.run(armazenamento.reservas_ativas("302"))) == 1
    # A própria, sim.
    assert asyncio.run(
        armazenamento.cancelar_reserva("101", area="quadra", data="2030-03-09")
    ) == "RSV-1377"


def test_disputa_concorrente_exatamente_uma_vence(banco_isolado):
    """Garantia 5: duas gravações simultâneas, uma reserva só."""

    async def disputa():
        resultados = await asyncio.gather(
            *[
                armazenamento.criar_reserva("101", "salao-de-festas", "2030-05-11")
                for _ in range(4)
            ]
        )
        return resultados

    resultados = asyncio.run(disputa())
    assert sum(r is not None for r in resultados) == 1
    ativas = asyncio.run(armazenamento.reservas_ativas("101"))
    assert sum(r["area"] == "salao-de-festas" and r["data"] == "2030-05-11" for r in ativas) == 1


def test_agenda_nunca_revela_dono(banco_isolado):
    assert asyncio.run(armazenamento.data_ocupada("salao-de-festas", "2030-03-16")) is True
    assert asyncio.run(armazenamento.data_ocupada("salao-de-festas", "2030-04-01")) is False
