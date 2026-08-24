"""Tests for the mcp_api schema validator."""

from mcp_api.validator import validate


def test_type_checks():
    schema = {"type": "integer"}
    assert validate(5, schema) == []
    assert validate(True, schema)[0]["message"].startswith("expected integer")
    assert validate("5", schema)[0]["message"].startswith("expected integer")
    assert validate([], {"type": "array"}) == []
    assert validate({}, {"type": "object"}) == []
    assert validate("x", {"type": "string"}) == []
    assert validate(False, {"type": "boolean"}) == []


def test_null_is_treated_as_unset():
    assert validate(None, {"type": "integer"}) == []
    assert (
        validate(
            {"a": None}, {"type": "object", "properties": {"a": {"type": "string"}}}
        )
        == []
    )


def test_enum():
    schema = {"type": "string", "enum": ["a", "b"]}
    assert validate("a", schema) == []
    errors = validate("c", schema)
    assert "is not one of" in errors[0]["message"]


def test_minimum_maximum():
    schema = {"type": "integer", "minimum": 0, "maximum": 23}
    assert validate(0, schema) == []
    assert validate(23, schema) == []
    assert "below minimum" in validate(-1, schema)[0]["message"]
    assert "above maximum" in validate(24, schema)[0]["message"]


def test_required_and_nested_paths():
    schema = {
        "type": "object",
        "properties": {
            "zone": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            }
        },
    }
    errors = validate({"zone": {}}, schema)
    assert errors == [
        {"path": "zone", "message": "required property 'name' is missing"}
    ]


def test_array_items_paths():
    schema = {"type": "array", "items": {"type": "integer"}}
    errors = validate([1, "x", 3], schema, path="ids")
    assert errors[0]["path"] == "ids[1]"


def test_pattern_properties():
    schema = {
        "type": "object",
        "patternProperties": {"^[0-9]+$": {"type": "boolean"}},
    }
    assert validate({"12": True}, schema) == []
    errors = validate({"12": "yes"}, schema)
    assert errors[0]["path"] == "12"


def test_unknown_keywords_ignored():
    schema = {
        "type": "string",
        "title": "T",
        "tooltip": "tip",
        "x-sync_to_indigo": True,
        "default": "d",
    }
    assert validate("ok", schema) == []
