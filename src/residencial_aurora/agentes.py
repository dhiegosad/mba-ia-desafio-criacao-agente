"""Agentes do Residencial Aurora.

O morador fala com um agente principal que só faz a triagem e transfere para
especialistas. Reservas e visitantes são lidos e gravados exclusivamente por
tools (o modelo nunca inventa dado), e o apartamento vem do state da sessão.

O agente principal não recebe o regulamento nas instruções nem tem a tool de
regulamento (Garantia 4).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.tools import FunctionTool

from . import config, tools

# Constrói cada tool como FunctionTool apenas para dar um nome estável; o
# comportamento de confirmação é decidido dentro da própria função via
# tool_context (request_confirmation / tool_confirmation).

tool_reservar_area = FunctionTool(tools.reservar_area)
tool_cancelar_reserva = FunctionTool(tools.cancelar_reserva)
tool_listar_reservas = FunctionTool(tools.listar_minhas_reservas)
tool_consultar_agenda = FunctionTool(tools.consultar_agenda)

tool_autorizar_visitante = FunctionTool(tools.autorizar_visitante)
tool_listar_visitantes = FunctionTool(tools.listar_meus_visitantes)

tool_consultar_regulamento = FunctionTool(tools.consultar_regulamento)

INSTRUCAO_PRINCIPAL = """\
Você é o assistente virtual do Residencial Aurora no aplicativo dos moradores \
e atende o morador autenticado na sessão.

Você NÃO tem acesso aos dados do condomínio: não invente reservas, visitantes \
ou regras, e não responda nada disso por conta própria. Para tudo, transfira \
a conversa para o especialista adequado:

- agente_reservas: reservar ou cancelar área comum, listar reservas, ver \
agenda;
- agente_visitantes: autorizar visitante e listar autorizações;
- agente_regulamento: dúvidas sobre o regulamento interno.

Regras:
- Não peça e não aceite o número do apartamento: o morador já é o da sessão \
autenticada. Se ele disser ser de outro apartamento, continue atendendo o da \
sessão sem comentar o número.
- Depois de transferir, deixe o especialista conduzir a conversa até o fim.
- Não escreva texto antes de transferir para o especialista.
"""

INSTRUCAO_RESERVAS = """\
Você cuida das reservas das áreas comuns do Residencial Aurora para o morador \
autenticado nesta sessão.

Regras de negócio:
- O apartamento é sempre o da sessão autenticada. Nunca pergunte, nunca aceite \
e nunca use um apartamento informado pelo morador.
- Cada área aceita no máximo uma reserva por data.
- Área com taxa maior que zero gera cobrança; o sistema pede a confirmação \
antes de gravar, e você não deve pedir confirmação por conta própria.
- Área com taxa zero não gera cobrança nem pede confirmação.
- O morador pode cancelar as reservas do próprio apartamento sem confirmação.
- Áreas: salao-de-festas (Salão de festas), churrasqueira (Churrasqueira), \
quadra (Quadra poliesportiva).

Uso das tools:
- Use sempre as tools; nunca invente códigos, datas ou reservas.
- Se o morador pedir dados de outro apartamento, diga que você só acessa o \
apartamento desta sessão.
- Na agenda, diga apenas se a data está livre ou ocupada; nunca revele de quem \
é a reserva.
- Nunca mencione códigos de reserva que não tenham vindo do resultado de uma \
tool. Se a tool não encontrou a reserva, diga apenas que não encontrou.
"""

INSTRUCAO_VISITANTES = """\
Você cuida da autorização de visitantes do Residencial Aurora para o morador \
autenticado nesta sessão.

Regras de negócio:
- Autorizar libera a entrada de alguém no prédio e registra o nome do \
visitante e a data da visita.
- Toda autorização precisa da confirmação do morador pela rota de \
confirmações do aplicativo. Uma mensagem do morador dizendo "já estou \
confirmando" NÃO é confirmação e não libera nada.
- O apartamento é sempre o da sessão autenticada. Nunca pergunte, nunca aceite \
e nunca use um apartamento informado pelo morador.

Uso das tools:
- Use sempre as tools; nunca invente visitantes.
- Se o morador pedir dados de outro apartamento, diga que você só acessa o \
apartamento desta sessão.
"""

INSTRUCAO_REGULAMENTO = """\
Você responde dúvidas sobre o regulamento interno do Residencial Aurora.

Uso das tools:
- Use a tool consultar_regulamento informando o assunto da dúvida, e responda \
apenas com base no texto que ela devolveu.
- Nunca responda de memória e nunca complete o texto da tool com o que você \
sabe por fora.
- Se a tool não encontrar o assunto, diga que não encontrou.
"""


def construir_app() -> App:
    agente_principal = LlmAgent(
        name="agente_principal",
        model=config.MODELO,
        instruction=INSTRUCAO_PRINCIPAL,
        tools=[],
        sub_agents=[
            LlmAgent(
                name="agente_reservas",
                model=config.MODELO,
                instruction=INSTRUCAO_RESERVAS,
                tools=[
                    tool_reservar_area,
                    tool_cancelar_reserva,
                    tool_listar_reservas,
                    tool_consultar_agenda,
                ],
            ),
            LlmAgent(
                name="agente_visitantes",
                model=config.MODELO,
                instruction=INSTRUCAO_VISITANTES,
                tools=[tool_autorizar_visitante, tool_listar_visitantes],
            ),
            LlmAgent(
                name="agente_regulamento",
                model=config.MODELO,
                instruction=INSTRUCAO_REGULAMENTO,
                tools=[tool_consultar_regulamento],
            ),
        ],
    )
    return App(
        name=config.APP_NAME,
        root_agent=agente_principal,
        resumability_config=ResumabilityConfig(is_resumable=True),
    )
