"""Tools do assistente.

Todas as tools que tocam reservas ou visitantes derivam o apartamento de
`tool_context.state["apartamento"]` — o valor gravado na criação da sessão.
Nenhuma tool aceita um apartamento escolhido pelo modelo (Garantia 2).

Ações que geram cobrança ou liberam acesso chamam
`tool_context.request_confirmation(...)` (Garantia 1): ficam pendentes até a
rota de confirmações responder, e são re-executadas pelo ADK com
`tool_context.tool_confirmation.confirmed` preenchido. O payload vira o
`detalhes` da confirmação exposta pela API.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from . import armazenamento, regulamento


def _apartamento(tool_context: ToolContext) -> str:
    apto = tool_context.state.get("apartamento")
    if not apto:
        raise ValueError("Sessão sem apartamento autenticado.")
    return str(apto)


# ---------------------------------------------------------------------------
# Reservas
# ---------------------------------------------------------------------------


async def listar_minhas_reservas(tool_context: ToolContext) -> dict[str, Any]:
    """Lista as reservas ativas do apartamento autenticado nesta sessão."""
    reservas = await armazenamento.reservas_ativas(_apartamento(tool_context))
    return {"reservas": reservas}


async def consultar_agenda(
    area: str, data: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Diz se uma área comum está livre ou ocupada em uma data (AAAA-MM-DD).

    Só revela a situação da agenda, nunca de quem é a reserva.
    """
    ocupada = await armazenamento.data_ocupada(area, data)
    return {"area": area, "data": data, "situacao": "ocupada" if ocupada else "livre"}


async def reservar_area(
    area: str, data: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Reserva uma área comum para o apartamento autenticado em uma data.

    Área com taxa maior que zero gera cobrança e pede confirmação antes de
    gravar; a própria tool solicita a confirmação. Área com taxa zero grava na
    hora.
    """
    if not armazenamento.area_existe(area):
        return {
            "status": "area_desconhecida",
            "mensagem": "Essa área não existe. Áreas: salao-de-festas, churrasqueira, quadra.",
        }
    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        taxa = armazenamento.taxa_da_area(area)
        if taxa > 0:
            tool_context.request_confirmation(
                hint=(
                    f"Reservar o(a) {area} em {data} gera cobrança de "
                    f"R$ {taxa:.2f}. Confirme a reserva."
                ),
                payload={"area": area, "data": data, "taxa": taxa},
            )
            return {"status": "aguardando_confirmacao"}
    elif not confirmacao.confirmed:
        return {"status": "recusada_pelo_morador"}

    resultado = await armazenamento.criar_reserva(
        _apartamento(tool_context), area, data
    )
    if resultado is None:
        return {
            "status": "indisponivel",
            "mensagem": "Essa área já está reservada nessa data.",
        }
    return {"status": "reservada", **resultado}


async def cancelar_reserva(
    tool_context: ToolContext,
    codigo: str | None = None,
    area: str | None = None,
    data: str | None = None,
) -> dict[str, Any]:
    """Cancela uma reserva ativa do apartamento autenticado.

    Aceita o código da reserva ou a área e a data. Reservas de outros
    apartamentos nunca são afetadas; se nada for encontrado, a tool responde
    que não encontrou.
    """
    cancelada = await armazenamento.cancelar_reserva(
        _apartamento(tool_context), codigo=codigo, area=area, data=data
    )
    if cancelada is None:
        return {
            "status": "nao_encontrada",
            "mensagem": "Não encontrei reserva ativa sua para esse espaço nessa data.",
        }
    return {"status": "cancelada", "codigo": cancelada}


# ---------------------------------------------------------------------------
# Visitantes
# ---------------------------------------------------------------------------


async def listar_meus_visitantes(tool_context: ToolContext) -> dict[str, Any]:
    """Lista os visitantes autorizados do apartamento autenticado nesta sessão."""
    visitantes = await armazenamento.visitantes(_apartamento(tool_context))
    return {"visitantes": visitantes}


async def autorizar_visitante(
    nome: str, data: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Autoriza a entrada de um visitante (nome e data AAAA-MM-DD) no prédio.

    Autorizar libera acesso, então sempre pede confirmação antes de gravar.
    Confirmar "pelo chat" não conta: a confirmação vem da rota de confirmações.
    """
    confirmacao = tool_context.tool_confirmation
    if confirmacao is None:
        tool_context.request_confirmation(
            hint=f"Autorizar a entrada de {nome} em {data}. Confirme a autorização.",
            payload={"nome": nome, "data": data},
        )
        return {"status": "aguardando_confirmacao"}
    if not confirmacao.confirmed:
        return {"status": "recusada_pelo_morador"}

    resultado = await armazenamento.autorizar_visitante(
        _apartamento(tool_context), nome, data
    )
    return {"status": "autorizado", **resultado}


# ---------------------------------------------------------------------------
# Regulamento
# ---------------------------------------------------------------------------


async def consultar_regulamento(assunto: str) -> dict[str, Any]:
    """Consulta o regulamento interno do condomínio.

    Informe o assunto da dúvida; a tool devolve apenas o capítulo do
    regulamento que trata desse assunto.
    """
    capitulo = regulamento.buscar_capitulo(assunto)
    if capitulo is None:
        return {"status": "nao_encontrado", "mensagem": "Não encontrei esse assunto no regulamento."}
    return {"status": "ok", "capitulo": capitulo["titulo"], "texto": capitulo["texto"]}
