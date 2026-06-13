import json

import pytest

from pipeline.llm.json_utils import parse_llm_json


def test_plain_json():
    assert parse_llm_json('{"category": "concert"}') == {"category": "concert"}


def test_json_fenced_with_language_tag():
    raw = '```json\n{\n  "category": "exhibition",\n  "confidence": 1.0\n}\n```'
    assert parse_llm_json(raw) == {"category": "exhibition", "confidence": 1.0}


def test_json_fenced_without_language_tag():
    raw = '```\n{"is_event": false}\n```'
    assert parse_llm_json(raw) == {"is_event": False}


def test_json_wrapped_in_prose():
    raw = 'Вот результат:\n{"category": "standup"}\nНадеюсь, помог!'
    assert parse_llm_json(raw) == {"category": "standup"}


def test_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json("definitely not json")
