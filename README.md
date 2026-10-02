# Residencial Aurora — assistente virtual

Assistente do aplicativo dos moradores do Residencial Aurora, feito com
**Google ADK 2.11.0** e **Gemini**. Um agente principal faz a triagem e
transfere para especialistas; as regras do condomínio são garantidas por código
(banco de dados, estado da sessão e confirmação fora do chat), não pela boa
vontade do modelo.

---

## Arquitetura

O app é um `App` do ADK (`src/residencial_aurora/agentes.py`) com um agente raiz
e três subagentes. O morador conversa só com o principal; ele transfere e sai de
cena.

```
morador ──► agente_principal (triagem, sem tools)
                 ├──► agente_reservas     (reservar, cancelar, listar, agenda)
                 ├──► agente_visitantes   (autorizar, listar)
                 └──► agente_regulamento  (consultar_regulamento)
```

### `agente_principal`

- **Responsabilidade:** identificar a intenção e transferir para o especialista.
- **Como é acionado:** é o `root_agent`; toda mensagem nova entra por ele.
- **Por que assim:** é o único ponto que recebe o texto do morador, então é onde
  a triagem fica isolada. Ele **não tem tools** e **não recebe o regulamento** na
  instrução — assim não consegue responder dados de reserva, visitante ou
  regulamento por conta própria, só encaminhar. A instrução ainda proíbe pedir
  ou aceitar número de apartamento do morador.
- **Definição:** [agentes.py:110-141](src/residencial_aurora/agentes.py#L110-L141)

### `agente_reservas`

- **Responsabilidade:** reservar e cancelar áreas comuns, listar as reservas do
  apartamento e consultar a agenda.
- **Como é acionado:** transferência do principal.
- **Por que separado:** é o dono das quatro tools que escrevem reserva. Isolar
  essas tools num agente só evita que outro agente receba uma tool de escrita que
  não é do seu assunto.
- **Tools:** `reservar_area`, `cancelar_reserva`, `listar_minhas_reservas`,
  `consultar_agenda`

### `agente_visitantes`

- **Responsabilidade:** autorizar visitante (nome + data) e listar as
  autorizações.
- **Como é acionado:** transferência do principal.
- **Por que separado:** autorizar libera acesso físico, então tem a sua própria
  exigência de confirmação. Deixar isso num agente próprio mantém a regra
  ("toda autorização precisa da confirmação do app") colada nas duas tools que
  mexem com isso.
- **Tools:** `autorizar_visitante`, `listar_meus_visitantes`

### `agente_regulamento`

- **Responsabilidade:** responder dúvidas do regulamento interno.
- **Como é acionado:** transferência do principal.
- **Por que separado:** é o único agente com a tool de regulamento. Concentrar a
  consulta aqui é o que permite ao principal ficar sem o texto do regulamento.
- **Tools:** `consultar_regulamento`

### Camada HTTP

`src/residencial_aurora/api.py` é uma API FastAPI fina sobre o `Runner` do ADK:
recebe a mensagem, roda o turno, devolve o texto e as confirmações pendentes. As
rotas de verificação (`/apartamentos/{apto}/reservas` e `/visitantes`) leem o
armazenamento direto, **sem passar pelo modelo**.

---

## Garantias

### Garantia 1 — ação que cobra ou libera acesso só executa após confirmação do sistema

A confirmação é pedida **dentro da tool**, pelo ADK, e só é respondida pela rota
de confirmações. Mensagem do morador dizendo "já estou confirmando" não é
confirmação: ela nunca chega à tool como `tool_confirmation`.

Em [tools.py:66-79](src/residencial_aurora/tools.py#L66-L79), `reservar_area`:

```python
confirmacao = tool_context.tool_confirmation
if confirmacao is None:
    taxa = armazenamento.taxa_da_area(area)
    if taxa > 0:
        tool_context.request_confirmation(
            hint=(f"Reservar o(a) {area} em {data} gera cobrança de R$ {taxa:.2f}. Confirme a reserva."),
            payload={"area": area, "data": data, "taxa": taxa},
        )
        return {"status": "aguardando_confirmacao"}
elif not confirmacao.confirmed:
    return {"status": "recusada_pelo_morador"}
```

`autorizar_visitante` faz o mesmo, sem condição de taxa — toda autorização libera
acesso ([tools.py:134-142](src/residencial_aurora/tools.py#L134-L142)).

A rota que responde só aceita um id **pendente nesta sessão**; qualquer outro
(inclusive já respondido) leva 409 ([api.py:168-192](src/residencial_aurora/api.py#L168-L192)):

```python
pendentes = _confirmacoes_pendentes(sessao.events)
if not any(p["id"] == corpo.id for p in pendentes):
    raise HTTPException(status_code=409, detail="Não existe confirmação pendente com esse id nesta sessão.")
```

**Por que não depende do modelo:** `request_confirmation` não grava nada — ele
registra um `FunctionCall` de `adk_request_confirmation` no log de eventos da
sessão e devolve `aguardando_confirmacao`. O INSERT só acontece numa segunda
execução da tool, e essa execução só existe quando o cliente manda um
`FunctionResponse` para aquele id pela rota de confirmações. O modelo não tem
tool nem instrução para "confirmar" — a confirmação é um evento do sistema, e a
pendência é conferida no log da sessão, não no texto da conversa.

### Garantia 2 — sessão presa a um apartamento, nunca vindo do prompt

O apartamento é gravado no `state` da sessão na criação
([api.py:148-157](src/residencial_aurora/api.py#L148-L157)):

```python
await servico_sessoes.create_session(
    app_name=config.APP_NAME, user_id=config.USER_ID,
    session_id=session_id, state={"apartamento": corpo.apartamento},
)
```

Toda tool deriva o apartamento do state — **nenhuma tool aceita um apartamento
como parâmetro** ([tools.py:23-27](src/residencial_aurora/tools.py#L23-L27)):

```python
def _apartamento(tool_context: ToolContext) -> str:
    apto = tool_context.state.get("apartamento")
    if not apto:
        raise ValueError("Sessão sem apartamento autenticado.")
    return str(apto)
```

E a agenda responde só a situação, nunca o dono
([armazenamento.py:140-148](src/residencial_aurora/armazenamento.py#L140-L148)):

```python
cur = await con.execute(
    "SELECT 1 FROM reservas WHERE area = ? AND data = ?"
    " AND cancelada_em IS NULL LIMIT 1", (area, data))
return await cur.fetchone() is not None
```

**Por que não depende do modelo:** não existe caminho de código em que o
apartamento venha do texto. As assinaturas das tools não têm esse parâmetro, o
`WHERE` do cancelamento sempre inclui `apartamento = ?`
([armazenamento.py:196](src/residencial_aurora/armazenamento.py#L196)), e a
agenda devolve um booleano — não há de quem revelar. Se o morador disser outro
apartamento, o valor é ignorado: o da sessão continua sendo usado.

### Garantia 3 — nada se perde no restart

Sessões e eventos ficam em SQLite pelo `DatabaseSessionService`
([api.py:31-34](src/residencial_aurora/api.py#L31-L34)); reservas e visitantes
ficam em `estado/aurora.db` ([armazenamento.py:46-56](src/residencial_aurora/armazenamento.py#L46-L56)).
No boot, `inicializar()` só recarrega `dados/` se a tabela de reservas estiver
vazia ([armazenamento.py:62-71](src/residencial_aurora/armazenamento.py#L62-L71)):

```python
cur = await con.execute("SELECT COUNT(*) AS n FROM reservas")
vazio = (await cur.fetchone())["n"] == 0
if vazio:
    await restaurar()
```

**Por que não depende do modelo:** persistência é do processo, não da conversa.
Os dois bancos são arquivos em `estado/`; reiniciar a API reabre os mesmos
arquivos, e como a tabela de reservas não está vazia, `dados/` não é recarregado
por cima. Uma sessão criada antes do restart continua existindo e continua
respondendo — inclusive uma confirmação pendente.

### Garantia 4 — regulamento é consultado, não carregado

O principal não recebe o regulamento na instrução
([agentes.py:33-52](src/residencial_aurora/agentes.py#L33-L52)) e não tem a tool.
A consulta devolve **um** capítulo ([regulamento.py:80-96](src/residencial_aurora/regulamento.py#L80-L96)):

```python
for cap in _carregar_capitulos():
    titulo, corpo = _termos(cap["titulo"]), _termos(cap["texto"])
    pontos = 3 * len(termos & titulo) + len(termos & corpo)
    if pontos > melhor_pontos:
        melhor, melhor_pontos = cap, pontos
return melhor if melhor_pontos else None
```

**Por que não depende do modelo:** o texto inteiro nunca entra em instrução nem
em evento — só o capítulo vencedor é devolvido pela tool, e é ele que vira o
resultado da função no log. Como a pontuação escolhe no máximo um capítulo, um
evento da sessão nunca contém capítulos de outros assuntos. A instrução do
`agente_regulamento` ainda manda responder só com o que a tool devolveu.

### Garantia 5 — dois moradores, uma reserva

A exclusividade é um índice único parcial no banco, não uma checagem em Python
([armazenamento.py:30-32](src/residencial_aurora/armazenamento.py#L30-L32)):

```sql
CREATE UNIQUE INDEX IF NOT EXISTS reserva_ativa_unica
  ON reservas(area, data) WHERE cancelada_em IS NULL;
```

A gravação roda num `BEGIN IMMEDIATE` e trata a violação como resultado normal
([armazenamento.py:151-179](src/residencial_aurora/armazenamento.py#L151-L179)):

```python
await con.execute("BEGIN IMMEDIATE")
...
except sqlite3.IntegrityError:
    await con.rollback()
    return None
```

O perdedor recebe `{"status": "indisponivel", "mensagem": "Essa área já está reservada nessa data."}`
([tools.py:84-88](src/residencial_aurora/tools.py#L84-L88)) — resposta normal, sem erro de servidor.

**Por que não depende do modelo:** a regra é imposta **no instante do INSERT**,
pelo índice. Mesmo que duas gravações confiram a agenda antes e as duas a vejam
livre, a segunda é recusada pelo banco. `BEGIN IMMEDIATE` + `busy_timeout` fazem
as duas transações serializarem em vez de correrem juntas. O modelo pode até
chamar a tool duas vezes; o banco deixa passar uma. O teste
`test_disputa_concorrente_exatamente_uma_vence` dispara 4 gravações simultâneas e
verifica que exatamente uma vence.

---

## Como rodar

### Pré-requisitos

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Uma chave do **Google AI Studio** (Gemini)

### Variáveis de ambiente

Copie o exemplo e preencha a chave:

```bash
cp .env.example .env
```

`.env` (fora do Git):

```bash
GOOGLE_API_KEY=sua-chave-do-google-ai-studio
AURORA_MODEL=gemini-3.8-flash
```

`AURORA_MODEL` é opcional; o padrão é `gemini-3.8-flash`. O app carrega o
`.env` sozinho na inicialização (`src/residencial_aurora/config.py`), então não é
preciso exportar a chave na mão.

### Restaurar os dados iniciais

```bash
uv run aurora restaurar
```

Recarrega reservas e visitantes de `dados/` e reinicia a sequência de códigos.
Rode isso sempre que quiser voltar ao estado do início do desafio.

### Subir a API

```bash
uv run aurora servir
```

Sobe em `http://localhost:8000`. Na primeira execução, se o banco estiver vazio,
os dados iniciais de `dados/` são carregados automaticamente.

### Exemplo de uso

```bash
# cria a sessão do apartamento 101
SID=$(curl -s -X POST localhost:8000/sessoes \
  -H 'content-type: application/json' -d '{"apartamento":"101"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["session_id"])')

# morador pede uma reserva que gera cobrança
curl -s -X POST localhost:8000/sessoes/$SID/mensagens \
  -H 'content-type: application/json' \
  -d '{"texto":"quero reservar o salão de festas para 2030-05-11"}'
# → devolve "confirmacoes_pendentes": [{"id":"...","acao":"reservar_area","detalhes":{...}}]

# confirma pelo aplicativo (rota de confirmações, não pelo chat)
curl -s -X POST localhost:8000/sessoes/$SID/confirmacoes \
  -H 'content-type: application/json' -d '{"id":"<id-da-pendencia>","confirmado":true}'

# confere o resultado direto no armazenamento, sem passar pelo modelo
curl -s localhost:8000/apartamentos/101/reservas
```

### Rotas

| Método | Rota | Para que serve |
|---|---|---|
| `POST` | `/sessoes` | cria a sessão e fixa o apartamento |
| `POST` | `/sessoes/{id}/mensagens` | manda uma mensagem do morador |
| `POST` | `/sessoes/{id}/confirmacoes` | responde uma confirmação pendente (409 se o id não estiver pendente) |
| `GET` | `/sessoes/{id}/eventos` | lista os eventos da sessão (404 se a sessão não existe) |
| `GET` | `/apartamentos/{apto}/reservas` | reservas ativas do apartamento |
| `GET` | `/apartamentos/{apto}/visitantes` | visitantes autorizados do apartamento |

### Testes

```bash
uv run pytest tests/ -q
```

Cobrem a restauração do estado inicial, a exclusividade sob concorrência e o
retrieval por capítulo do regulamento.
