"""Self-check do retrieval do regulamento (Garantia 4)."""

from residencial_aurora import regulamento


def test_assuntos_acham_o_capitulo_certo():
    casos = {
        "horario da piscina aos domingos": "Piscina",
        "posso ter cachorro": "Animais",
        "estacionar na garagem": "Garagem",
        "onde descarto o lixo": "lixo",
        "posso fazer reforma": "Obras",
        "barulho depois das 22h": "Silêncio",
    }
    for pergunta, esperado in casos.items():
        cap = regulamento.buscar_capitulo(pergunta)
        assert cap is not None, pergunta
        assert esperado.lower() in cap["titulo"].lower(), (pergunta, cap["titulo"])


def test_resposta_de_piscina_traz_horario_de_domingo():
    cap = regulamento.buscar_capitulo("até que horas a piscina funciona aos domingos")
    assert "20h" in cap["texto"]
