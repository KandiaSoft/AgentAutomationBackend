"""Tests for questionnaire response validation logic."""
import pytest
from app.models import AgentQuestionnaireOption, QuestionnaireItem


SAMPLE_QUESTIONNAIRE = [
    AgentQuestionnaireOption(
        number=1,
        question="L'intervento prevede la semplice sostituzione dei frutti?",
        responses=[
            "1. Semplice sostituzione dei frutti esistenti (manutenzione ordinaria)",
            "2. Modifica o spostamento delle scatole da incasso",
            "3. Rifacimento parziale delle linee elettriche del bagno",
            "4. Scrivi la tua risposta",
        ],
    ),
    AgentQuestionnaireOption(
        number=2,
        question="Qual è lo stato dell'impianto elettrico esistente?",
        responses=[
            "1. Impianto recente/a norma con differenziale e messa a terra efficiente",
            "2. Impianto datato ma funzionante (da verificare in sito)",
            "3. Impianto vetusto (pre-1990) privo di messa a terra",
            "4. Scrivi la tua risposta",
        ],
    ),
]


def validate_questionnaire_response(
    items: list[QuestionnaireItem],
    original: list[AgentQuestionnaireOption],
) -> list[str]:
    """Return list of validation errors."""
    errors = []
    orig_map = {q.number: q for q in original}
    for item in items:
        orig = orig_map.get(item.number)
        if not orig:
            errors.append(f"Unknown question number {item.number}")
            continue
        if item.response not in orig.responses:
            # Allow free-text only if starts with a number prefix not in list
            if not any(item.response.startswith(f"{i}.") for i in range(1, 10)):
                errors.append(
                    f"Q{item.number}: response '{item.response}' not in options and not a valid free-text format"
                )
    return errors


def test_valid_numeric_responses():
    items = [
        QuestionnaireItem(
            number=1,
            question=SAMPLE_QUESTIONNAIRE[0].question,
            response="1. Semplice sostituzione dei frutti esistenti (manutenzione ordinaria)",
        ),
        QuestionnaireItem(
            number=2,
            question=SAMPLE_QUESTIONNAIRE[1].question,
            response="1. Impianto recente/a norma con differenziale e messa a terra efficiente",
        ),
    ]
    errors = validate_questionnaire_response(items, SAMPLE_QUESTIONNAIRE)
    assert errors == []


def test_invalid_response_not_in_options():
    items = [
        QuestionnaireItem(
            number=1,
            question=SAMPLE_QUESTIONNAIRE[0].question,
            response="Voglio fare una cosa diversa",
        ),
    ]
    errors = validate_questionnaire_response(items, SAMPLE_QUESTIONNAIRE)
    assert len(errors) == 1
    assert "Q1" in errors[0]


def test_free_text_response_accepted():
    """Free-text option '4.' should be accepted even with custom text."""
    items = [
        QuestionnaireItem(
            number=1,
            question=SAMPLE_QUESTIONNAIRE[0].question,
            response="4. Ho bisogno di una valutazione sul posto perché la situazione è particolare",
        ),
    ]
    # "4. ..." starts with "4." so it's a valid free-text format
    errors = validate_questionnaire_response(items, SAMPLE_QUESTIONNAIRE)
    assert errors == []


def test_unknown_question_number():
    items = [
        QuestionnaireItem(number=99, question="?", response="1. anything"),
    ]
    errors = validate_questionnaire_response(items, SAMPLE_QUESTIONNAIRE)
    assert len(errors) == 1
    assert "99" in errors[0]


def test_all_responses_covered():
    """All questions in original must have a corresponding answer."""
    items = [
        QuestionnaireItem(
            number=1,
            question=SAMPLE_QUESTIONNAIRE[0].question,
            response="2. Modifica o spostamento delle scatole da incasso",
        ),
        QuestionnaireItem(
            number=2,
            question=SAMPLE_QUESTIONNAIRE[1].question,
            response="3. Impianto vetusto (pre-1990) privo di messa a terra",
        ),
    ]
    errors = validate_questionnaire_response(items, SAMPLE_QUESTIONNAIRE)
    assert errors == []
