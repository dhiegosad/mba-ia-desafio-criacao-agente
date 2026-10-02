"""Caminhos e constantes do projeto."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]

load_dotenv(RAIZ / ".env")
"""Carrega GOOGLE_API_KEY do .env local (fora do Git)."""

DADOS = RAIZ / "dados"
"""Dados iniciais do condomínio. Somente leitura, nunca alterados."""

ESTADO = RAIZ / "estado"
"""Estado de execução (SQLite). Fora de dados/ e fora do Git."""

BANCO_CONDOMINIO = ESTADO / "aurora.db"
"""Reservas, visitantes e a sequência de códigos."""

BANCO_SESSOES = ESTADO / "sessoes.db"
"""Sessões e eventos do ADK."""

APP_NAME = "residencial_aurora"
USER_ID = "morador"
"""O morador autenticado. O apartamento vive no state da sessão."""

MODELO = os.getenv("AURORA_MODEL", "gemini-2.5-flash")

INICIO_CODIGO_RESERVA = 5000
"""Primeiro valor da sequência de códigos novos. Acima de qualquer código inicial."""
