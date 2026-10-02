"""Comandos da linha de comando: `aurora servir` e `aurora restaurar`."""

from __future__ import annotations

import asyncio
import sys

from . import armazenamento


def main() -> None:
    comando = sys.argv[1] if len(sys.argv) > 1 else "servir"
    if comando == "restaurar":
        asyncio.run(armazenamento.restaurar())
        print(
            "Dados restaurados: reservas e visitantes voltaram ao estado de"
            " dados/ (sequência de códigos reiniciada)."
        )
        return
    if comando == "servir":
        import uvicorn

        uvicorn.run("residencial_aurora.api:app", host="0.0.0.0", port=8000)
        return
    print(
        f"Comando desconhecido: {comando!r}.\n"
        "Uso: uv run aurora servir | uv run aurora restaurar",
        file=sys.stderr,
    )
    sys.exit(1)
