"""Consulta ao regulamento interno.

O regulamento é longo e, se o texto inteiro entrasse no histórico, encareceria
todas as chamadas seguintes. A tool consultar_regulamento devolve só o capítulo
que trata do assunto perguntado (Garantia 4): o evento gravado na sessão nunca
contém capítulos de outros assuntos, e o agente principal nunca recebe o
regulamento nas instruções.
"""

from __future__ import annotations

import re
import unicodedata

from . import config

_STOPWORDS = {
    "este", "para", "com", "por", "uma", "ser", "estao", "sao", "nao", "que",
    "dos", "das", "aos", "nas", "nos", "sobre", "entre", "como", "mais",
    "sua", "seu", "toda", "todo", "todos", "todas", "sera", "devem", "deve",
    "posso", "pode", "poder", "quero", "preciso", "qual", "quais", "quando",
    "onde", "existe", "existem", "existe?",
}

# Sinônimos que aproximam o assunto digitado do vocabulário dos capítulos.
_SINONIMOS = {
    "cachorro": "animal", "cachorros": "animal", "cao": "animal",
    "caes": "animal", "gato": "animal", "gatos": "animal", "pet": "animal",
    "pets": "animal", "domestico": "animal", "domesticos": "animal",
    "animal": "animal", "animais": "animal", "bicho": "animal",
    "bichos": "animal", "mascote": "animal",
    "carro": "garagem", "carros": "garagem", "veiculo": "garagem",
    "veiculos": "garagem", "estacionar": "garagem",
    "estacionamento": "garagem", "vaga": "garagem", "vagas": "garagem",
    "bicicleta": "garagem", "bicicletas": "garagem",
    "reciclaveis": "lixo", "reciclagem": "lixo", "reciclar": "lixo",
    "entulho": "lixo", "coleta": "lixo", "oleo": "lixo",
    "reforma": "obra", "reformas": "obra", "construcao": "obra",
    "mudancas": "mudanca",
    "barulho": "silencio", "ruido": "silencio", "ruidos": "silencio",
    "festa": "festas", "festas": "festas", "salao": "festas",
    "churrasco": "churrasqueira",
    "visitantes": "visitante", "portaria": "visitante",
    "seguranca": "visitante", "encomenda": "visitante",
    "encomendas": "visitante", "entregas": "visitante",
}

_capitulos: list[dict[str, str]] | None = None


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def _termos(texto: str) -> set[str]:
    termos: set[str] = set()
    for t in re.findall(r"[a-z0-9]+", _normalizar(texto)):
        if len(t) < 4 or t in _STOPWORDS:
            continue
        canonico = _SINONIMOS.get(t, t)
        termos.add(canonico)
        # Casa plurais regulares ("piscinas" -> "piscina").
        if canonico.endswith("s") and len(canonico) > 4:
            termos.add(canonico[:-1])
    return termos


def _carregar_capitulos() -> list[dict[str, str]]:
    global _capitulos
    if _capitulos is None:
        bruto = (config.DADOS / "regulamento.md").read_text(encoding="utf-8")
        _capitulos = []
        for bloco in re.split(r"(?m)^## ", bruto)[1:]:
            titulo = bloco.splitlines()[0].strip()
            _capitulos.append({"titulo": titulo, "texto": bloco.strip()})
    return _capitulos


def buscar_capitulo(assunto: str) -> dict[str, str] | None:
    """Devolve o capítulo cujo título/texto mais se aproxima do assunto.

    Título pesa 3x porque é a âncora do assunto ("Capítulo IV: Piscina").
    A pontuação só existe para escolher um capítulo; nunca sobe para o evento
    nada além do capítulo vencedor.
    """
    termos = _termos(assunto)
    if not termos:
        return None
    melhor, melhor_pontos = None, 0
    for cap in _carregar_capitulos():
        titulo, corpo = _termos(cap["titulo"]), _termos(cap["texto"])
        pontos = 3 * len(termos & titulo) + len(termos & corpo)
        if pontos > melhor_pontos:
            melhor, melhor_pontos = cap, pontos
    return melhor if melhor_pontos else None
