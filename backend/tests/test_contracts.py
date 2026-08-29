import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).parents[2]
CONTRACTS = ROOT / "contracts" / "v1"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_event_contract_accepts_valid_example_and_rejects_invalid_example() -> None:
    schema = load_json(CONTRACTS / "event-envelope.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(load_json(CONTRACTS / "examples" / "event.valid.json"))
    with pytest.raises(ValidationError):
        validator.validate(load_json(CONTRACTS / "examples" / "event.invalid.json"))


@pytest.mark.parametrize(
    "schema_name",
    [
        "event-envelope.schema.json",
        "problem.schema.json",
        "config.schema.json",
        "report.schema.json",
        "geojson.schema.json",
    ],
)
def test_contract_schema_is_valid_draft_2020_12(schema_name: str) -> None:
    Draft202012Validator.check_schema(load_json(CONTRACTS / schema_name))


def test_report_examples_validate() -> None:
    validator = Draft202012Validator(
        load_json(CONTRACTS / "report.schema.json"),
        format_checker=FormatChecker(),
    )
    validator.validate(load_json(CONTRACTS / "examples" / "report.valid.json"))
    validator.validate(load_json(CONTRACTS / "examples" / "report.incomplete.json"))
