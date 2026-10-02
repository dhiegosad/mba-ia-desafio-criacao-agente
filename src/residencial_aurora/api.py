"""API HTTP do assistente do Residencial Aurora.

Rotas de conversa (contrato do enunciado) e rotas de verificação, que leem os
dados do condomínio direto do armazenamento, sem passar pelo modelo.

A confirmação (Garantia 1) não é conversa: a rota de confirmações só aceita um
id que esteja pendente nesta sessão e responde 409 para qualquer outro. A
resposta vira um FunctionResponse de `adk_request_confirmation`, que é como o
ADK retoma a execução no agente que pediu a confirmação.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from pydantic import BaseModel

from . import agentes, armazenamento, config

NOME_CONFIRMACAO = "adk_request_confirmation"

config.ESTADO.mkdir(parents=True, exist_ok=True)

servico_sessoes = DatabaseSessionService(
    db_url=f"sqlite+aiosqlite:///{config.BANCO_SESSOES}"
)
runner = Runner(app=agentes.construir_app(), session_service=servico_sessoes)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await armazenamento.inicializar()
    yield


app = FastAPI(title="Residencial Aurora", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Contrato de entrada
# ---------------------------------------------------------------------------


class CriarSessao(BaseModel):
    apartamento: str


class Mensagem(BaseModel):
    texto: str


class RespostaConfirmacao(BaseModel):
    id: str
    confirmado: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _sessao(session_id: str):
    return await servico_sessoes.get_session(
        app_name=config.APP_NAME, user_id=config.USER_ID, session_id=session_id
    )


async def _sessao_ou_404(session_id: str):
    sessao = await _sessao(session_id)
    if sessao is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    return sessao


async def _executar(session_id: str, mensagem: types.Content) -> list[Event]:
    eventos: list[Event] = []
    async for evento in runner.run_async(
        user_id=config.USER_ID, session_id=session_id, new_message=mensagem
    ):
        eventos.append(evento)
    return eventos


def _texto_resposta(eventos: list[Event]) -> str:
    """Texto final do turno: o último evento de texto que não pede tool."""
    final: str | None = None
    fallback: list[str] = []
    for evento in eventos:
        if evento.author == "user" or not evento.content or not evento.content.parts:
            continue
        textos = [p.text for p in evento.content.parts if p.text]
        if not textos:
            continue
        fallback.extend(textos)
        if not evento.get_function_calls() and not evento.partial:
            final = "\n".join(textos)
    return (final if final is not None else "\n".join(fallback)).strip()


def _confirmacoes_pendentes(eventos: list[Event]) -> list[dict[str, Any]]:
    """Confirmações abertas na sessão, no formato exposto pela API."""
    respondidas = {
        fr.id
        for evento in eventos
        if evento.author == "user"
        for fr in evento.get_function_responses()
        if fr.id
    }
    pendentes: list[dict[str, Any]] = []
    for evento in eventos:
        for fc in evento.get_function_calls():
            if fc.name != NOME_CONFIRMACAO or not fc.id or fc.id in respondidas:
                continue
            args = fc.args or {}
            original = args.get("originalFunctionCall") or {}
            confirmacao = args.get("toolConfirmation") or {}
            pendentes.append(
                {
                    "id": fc.id,
                    "acao": original.get("name", ""),
                    "detalhes": confirmacao.get("payload") or {},
                }
            )
    return pendentes


async def _resposta(session_id: str, eventos: list[Event]) -> dict[str, Any]:
    sessao = await _sessao(session_id)
    eventos_sessao = list(sessao.events) if sessao else []
    return {
        "resposta": _texto_resposta(eventos),
        "confirmacoes_pendentes": _confirmacoes_pendentes(eventos_sessao),
    }


# ---------------------------------------------------------------------------
# Rotas de conversa
# ---------------------------------------------------------------------------


@app.post("/sessoes", status_code=201)
async def criar_sessao(corpo: CriarSessao) -> dict[str, str]:
    session_id = uuid.uuid4().hex
    await servico_sessoes.create_session(
        app_name=config.APP_NAME,
        user_id=config.USER_ID,
        session_id=session_id,
        state={"apartamento": corpo.apartamento},
    )
    return {"session_id": session_id}


@app.post("/sessoes/{session_id}/mensagens")
async def enviar_mensagem(session_id: str, corpo: Mensagem) -> dict[str, Any]:
    await _sessao_ou_404(session_id)
    conteudo = types.Content(role="user", parts=[types.Part(text=corpo.texto)])
    eventos = await _executar(session_id, conteudo)
    return await _resposta(session_id, eventos)


@app.post("/sessoes/{session_id}/confirmacoes")
async def responder_confirmacao(
    session_id: str, corpo: RespostaConfirmacao
) -> dict[str, Any]:
    sessao = await _sessao_ou_404(session_id)
    pendentes = _confirmacoes_pendentes(sessao.events)
    if not any(p["id"] == corpo.id for p in pendentes):
        raise HTTPException(
            status_code=409,
            detail="Não existe confirmação pendente com esse id nesta sessão.",
        )
    conteudo = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=corpo.id,
                    name=NOME_CONFIRMACAO,
                    response={"confirmed": corpo.confirmado},
                )
            )
        ],
    )
    eventos = await _executar(session_id, conteudo)
    return await _resposta(session_id, eventos)


@app.get("/sessoes/{session_id}/eventos")
async def ver_eventos(session_id: str) -> list[dict[str, Any]]:
    sessao = await _sessao_ou_404(session_id)
    return [evento.model_dump(mode="json", exclude_none=True) for evento in sessao.events]


# ---------------------------------------------------------------------------
# Rotas de verificação
# ---------------------------------------------------------------------------


@app.get("/apartamentos/{apartamento}/reservas")
async def reservas_do_apartamento(apartamento: str) -> list[dict[str, Any]]:
    return await armazenamento.reservas_ativas(apartamento)


@app.get("/apartamentos/{apartamento}/visitantes")
async def visitantes_do_apartamento(apartamento: str) -> list[dict[str, Any]]:
    return await armazenamento.visitantes(apartamento)
