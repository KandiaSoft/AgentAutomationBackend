# AGENTS.md — Backend AI agent documentation

This file describes how AI models are used inside AgentAutomaton's backend: what calls are made to Google Gemini, what the structured outputs look like, how personas shape behaviour, and how the real preventivatore AI agent is called.

---

## Two distinct "agents" in this system

| Agent | Model | Role |
|---|---|---|
| **preventivatore AI** | Edilnet's hosted LLM (external) | The system under test. Plays the role of a knowledgeable Italian contractor who quotes construction work. |
| **Gemini client simulator** | `gemini-2.5-flash` (configurable) | Synthetic client. Reads agent responses and decides what to say next, including answering structured questionnaires. |

---

## preventivatore AI — the agent under test

### Endpoint

```
POST https://test-agent-prev-ai-777.edilnet.it/invoke_agent
```

### Request schema

```jsonc
{
  "user_id": "test-user-001",         // static, from AGENT_USER_ID env var
  "username": "Test Client",          // static, from AGENT_USERNAME env var
  "thread_id": "uuid4",               // unique per simulation, persists across turns
  "question": "string",               // client's free-text message (empty when questionnaire)
  "interrupt": 0,                     // 0 = normal turn; 1 = responding to questionnaire/interrupt
  "questionnaire": []                 // array of {number, question, response} (empty when free text)
}
```

The `thread_id` is a UUID4 generated once per simulation and sent on every turn. It is the agent's session key — it uses it to maintain conversation state on its end.

### Response schema

```jsonc
{
  "answer": "string",                 // agent's text reply to the client
  "understanding": "string",          // agent's internal summary of the situation
  "is_questionnaire": true,           // true if agent wants structured answers
  "has_interrupt": false,             // true if client must respond with interrupt=1
  "finished": false,                  // true when quote is complete
  "short_codes": [],                  // populated only when finished=true
  "questionnaire": [                  // populated only when is_questionnaire=true
    {
      "number": 1,
      "question": "Quante stanze?",
      "responses": ["1. Una stanza", "2. Due stanze", "3. Tre o più", "4. Scrivi la tua risposta"]
    }
  ],
  "tokens": [
    { "in_tokens": 1200, "out_tokens": 340, "model": "gemini-..." }
  ],
  "status": "success"
}
```

### `short_codes` structure (when `finished: true`)

```jsonc
[
  {
    "expert_name": "Idraulico",
    "elaborations": [
      {
        "short_code": "IMP.00024",
        "extended_description": "Fornitura e posa sanitari...",
        "reference_currency_price": "32,17 €",
        "unit_of_measure": "cad",
        "quantity": 2
      }
    ]
  }
]
```

Prices are formatted in Italian locale (`"32,17 €"`). The frontend `ShortCodesTable` component parses them by stripping non-numeric characters then replacing `,` with `.`.

### State machine

```
PENDING ──► RUNNING ──► (loop) ──► FINISHED
                                └──► ERROR
                                └──► STOPPED (cancel)
```

The turn loop:
1. **Client turn** — send `question`, `interrupt=0`, `questionnaire=[]`
2. **Agent turn** — receive `AgentResponse`
3. If `finished=true` → save `short_codes`, exit
4. Wait random delay (`delay_ms[0]`–`delay_ms[1]` ms)
5. **Gemini decides** next client turn → go to 1

---

## Gemini client simulator

File: `app/gemini_client.py`

### GeminiClient class

```python
class GeminiClient:
    async def answer_questionnaire(...) -> tuple[list[QuestionnaireItem], str]
    async def generate_reply(...) -> tuple[str, str]
    async def generate_text(prompt: str) -> str
```

Both `answer_questionnaire` and `generate_reply` return `(content, reasoning)` where `reasoning` is Gemini's explanation of why it chose that response (stored in `client_reasoning` in the DB, visible in the UI).

### Structured output (Gemini JSON mode)

Both methods use `response_mime_type="application/json"` with a `response_schema` to force Gemini to return a valid JSON object. This avoids brittle text parsing.

#### Questionnaire schema

```json
{
  "type": "object",
  "properties": {
    "questionnaire": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "number": { "type": "integer" },
          "question": { "type": "string" },
          "response": { "type": "string" }
        },
        "required": ["number", "question", "response"]
      }
    },
    "reasoning": { "type": "string" }
  },
  "required": ["questionnaire", "reasoning"]
}
```

Gemini must copy the chosen option text **exactly**, including the numeric prefix (`"1. Una stanza"`, not `"Una stanza"` and not a translation). This is enforced in both the system prompt and the user message via repeated explicit instructions.

#### Free-text reply schema

```json
{
  "type": "object",
  "properties": {
    "question": { "type": "string" },
    "reasoning": { "type": "string" }
  },
  "required": ["question", "reasoning"]
}
```

The `question` field contains the client's next message, written in the selected `language`. The `reasoning` field can be in English.

### Scenario generation schema

`generate_text()` is used without a schema — plain text output. Prompt instructs Gemini to produce 1–3 sentences in the target language with no preamble.

---

## Persona system

File: `app/personas.py`

### Design principle

Persona prompts are written in English regardless of the simulated client's language. This avoids model confusion when the output language differs from the system prompt language. The language instruction is injected via a template:

```python
_BASE_RULE_TEMPLATE = """
You are simulating a client requesting a construction/renovation quote from an Italian contractor.
Write all your messages in {lang_name}.
When you receive a questionnaire with numbered options, ALWAYS choose one of the provided options.
Copy the response text in the 'response' field using the EXACT option text including the numeric prefix (e.g. "1. testo").
Do NOT translate the questionnaire option text — copy it verbatim.
Use the free-text option (e.g. "4. Write your answer") ONLY if no option fits your scenario.
Do not explain your choices. Respond directly as a real client would in a chat.
"""
```

The `{lang_name}` placeholder is resolved by `get_system_prompt(persona_key, language)` using:

```python
LANGUAGE_NAMES = {"it": "Italian", "en": "English", "es": "Spanish"}
```

### Personas

| Key | Trait description |
|---|---|
| `homeowner_basic` | No technical knowledge, 1–2 sentence answers, cooperative but concise |
| `homeowner_technical` | Uses correct construction terminology (screed, slab, conduit, panel), provides technical details |
| `indecisive` | Sometimes asks for clarification, occasionally adds new details mid-conversation |
| `terse` | Bare minimum responses, always picks a numeric questionnaire option, no pleasantries |
| `detail_oriented` | Provides extensive context, uses free-text questionnaire answer when no option captures the full situation |

### Adding a new persona

1. Add an entry to `_PERSONA_TRAITS` in `personas.py`:
   ```python
   "my_persona": {
       "label": "Display name (Italian)",
       "description": "One-line description (Italian)",
       "traits": """English prompt describing how the client behaves..."""
   }
   ```
2. No other changes needed — the API and frontend pick it up automatically via `/api/personas`.

---

## Scenario resolution

`ClientSimulator._resolve_scenario()` selects the initial client message via priority:

1. **`scenario_text`** — use verbatim (user-entered free text)
2. **`generate_scenario=True`** — call `generate_random_scenario(persona_key, language)` which calls `gemini.generate_text()`
3. **`scenario_key`** — look up `SCENARIOS[scenario_key]["text"]`
4. If none match → raise `ValueError` (caught by the caller and stored as an error)

The resolved text becomes the client's very first message and is stored as `initial_request` in the DB.

### Adding a new catalog scenario

Add an entry to `SCENARIOS` in `scenarios.py`:

```python
"my_scenario_key": {
    "label": "Human-readable label",
    "category": "category_string",
    "text": "Italian text of the renovation request sent as first message.",
}
```

---

## Conversation history format

`ClientSimulator._history` is a list of dicts passed to Gemini calls. `_format_history()` in `gemini_client.py` renders it as plain text:

```
CLIENT: Vorrei ristrutturare il bagno...
AGENT: Capito, ho alcune domande...
CLIENT: 1. Due stanze
AGENT: Perfetto. Ora mi dica...
```

Only the latest questionnaire/answer is passed as the "current question" separately; the full history provides context for Gemini to maintain persona consistency across turns.

---

## Token accounting

The agent's response includes a `tokens` array. Each element has `in_tokens`, `out_tokens`, and `model`. These are summed per turn and accumulated into `total_in_tokens` / `total_out_tokens` on the simulation row. Gemini tokens for the client side are not currently tracked (the Google Gemini SDK response object isn't parsed for usage metadata).

---

## Error handling

| Exception | Where caught | Result |
|---|---|---|
| `asyncio.CancelledError` | `ClientSimulator.run()` | `status='stopped'`, WS broadcast |
| `httpx.ReadTimeout` / `ConnectTimeout` | `PreventivatoreClient.invoke()` | Retry up to `AGENT_MAX_RETRIES` times, then re-raise |
| `httpx.HTTPStatusError` | `PreventivatoreClient.invoke()` | Re-raise with response body in message |
| Any other `Exception` | `ClientSimulator.run()` | `status='error'`, error message persisted, WS broadcast, re-raise |
| Re-raised exceptions | `SimulationManager._run_with_semaphore()` | Suppressed to avoid asyncio "Task exception was never retrieved" warnings |
