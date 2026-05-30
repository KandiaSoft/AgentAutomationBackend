from __future__ import annotations
from app.models import Scenario
from app.personas import LANGUAGE_NAMES

SCENARIOS: dict[str, dict] = {
    "bagno_completo": {
        "label": "Rifacimento completo bagno 8mq",
        "category": "bagno",
        "text": "Rifacimento completo bagno 8mq: demolizione pavimento e rivestimenti esistenti, nuovi impianti idraulici ed elettrici, posa nuove piastrelle, sanitari e rubinetteria.",
    },
    "elettrico_bagno": {
        "label": "Interruttore e presa in bagno",
        "category": "elettrico",
        "text": "Vorrei cambiare un interruttore della luce in bagno. Devo anche cambiare una presa elettrica con messa a terra nello stesso bagno.",
    },
    "piastrelle_bagno": {
        "label": "Sostituzione piastrelle bagno 3x5",
        "category": "rivestimenti",
        "text": "Devo sostituire tutte le piastrelle del pavimento del mio bagno; il mio bagno misura 3 metri x 5 metri.",
    },
    "riscaldamento_pavimento": {
        "label": "Riscaldamento a pavimento 100mq",
        "category": "impianti",
        "text": "Impianto di riscaldamento a pavimento in appartamento di 100 m2, tutte le stanze.",
    },
    "cartongesso": {
        "label": "Cartongesso divisori appartamento",
        "category": "muratura",
        "text": "Posa e fornitura in opera di cartongesso su appartamento per creare divisori di tutte le stanze.",
    },
    "cucina_completa": {
        "label": "Ristrutturazione cucina 12mq",
        "category": "cucina",
        "text": "Ristrutturazione completa cucina di 12mq: smontaggio cucina esistente, demolizione pareti non portanti, nuovo impianto elettrico e idraulico, posa piastrelle e montaggio nuova cucina.",
    },
    "tetto_coibentazione": {
        "label": "Coibentazione tetto piano",
        "category": "isolamento",
        "text": "Devo isolare termicamente il tetto piano della mia villetta di 120mq per ridurre le dispersioni di calore in inverno.",
    },
    "infissi_sostituzione": {
        "label": "Sostituzione infissi appartamento",
        "category": "infissi",
        "text": "Sostituzione di tutti gli infissi del mio appartamento al 3° piano, 8 finestre e 2 porte finestre, con infissi in PVC a doppio vetro.",
    },
    "impianto_elettrico_appartamento": {
        "label": "Impianto elettrico completo appartamento 80mq",
        "category": "elettrico",
        "text": "Rifacimento completo impianto elettrico in appartamento di 80mq, compreso quadro elettrico, cablaggio, punti luce, prese e interruttori in tutte le stanze.",
    },
    "pittura_interna": {
        "label": "Pittura interna appartamento 70mq",
        "category": "finiture",
        "text": "Tinteggiatura interna completa appartamento 70mq: preparazione superfici, stuccatura, due mani di pittura lavabile su pareti e soffitti di tutti i locali.",
    },
}


def get_scenario_list() -> list[Scenario]:
    return [
        Scenario(key=k, label=v["label"], text=v["text"], category=v["category"])
        for k, v in SCENARIOS.items()
    ]


async def generate_random_scenario(persona_key: str | None = None, language: str = "it") -> str:
    from app.gemini_client import gemini
    lang_name = LANGUAGE_NAMES.get(language, "Italian")
    prompt = (
        f"Generate a short construction or renovation quote request for an Italian contractor, "
        f"written as if a client is typing via chat. "
        f"Write the request in {lang_name}. "
        f"It should be realistic and 1-3 sentences long. "
        f"Reply with ONLY the request, no other words."
    )
    return await gemini.generate_text(prompt)
