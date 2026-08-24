"""
Hand-rolled JSON-schema validator for the Auto Lights config schema.

Covers exactly the keywords config_schema.json uses: type, enum, minimum,
maximum, properties, required, items, patternProperties. Unknown keywords
(title, tooltip, default, x-*, $schema) are ignored. A dependency-free
walker is used instead of the jsonschema package because Indigo plugins
cannot easily bundle compiled transitive dependencies.

Errors are returned as {"path": "zones[2].behavior_settings.lock_duration",
"message": "..."} dicts so an AI caller can self-correct precisely.
"""

import re
from typing import Any, Dict, List

# bool is a subclass of int in Python; integer/number checks must exclude it
_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def validate(
    instance: Any, schema: Dict[str, Any], path: str = ""
) -> List[Dict[str, str]]:
    """Validate `instance` against `schema`, returning a list of errors."""
    errors: List[Dict[str, str]] = []
    label = path or "(root)"

    # null is treated as "unset" everywhere: real configs carry None values
    # written by the web UI (WTForms), and the plugin normalizes them on load
    if instance is None:
        return errors

    expected_type = schema.get("type")
    if expected_type is not None:
        check = _TYPE_CHECKS.get(expected_type)
        if check is not None and not check(instance):
            errors.append(
                {
                    "path": label,
                    "message": f"expected {expected_type}, got {type(instance).__name__}",
                }
            )
            return errors  # type mismatch makes deeper checks meaningless

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(
            {
                "path": label,
                "message": f"value {instance!r} is not one of {schema['enum']!r}",
            }
        )

    if "minimum" in schema and isinstance(instance, (int, float)):
        if not isinstance(instance, bool) and instance < schema["minimum"]:
            errors.append(
                {
                    "path": label,
                    "message": f"value {instance} is below minimum {schema['minimum']}",
                }
            )
    if "maximum" in schema and isinstance(instance, (int, float)):
        if not isinstance(instance, bool) and instance > schema["maximum"]:
            errors.append(
                {
                    "path": label,
                    "message": f"value {instance} is above maximum {schema['maximum']}",
                }
            )

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(
                    {"path": label, "message": f"required property '{key}' is missing"}
                )
        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in instance:
                errors.extend(
                    validate(
                        instance[key], sub_schema, f"{path}.{key}" if path else key
                    )
                )
        for pattern, sub_schema in schema.get("patternProperties", {}).items():
            regex = re.compile(pattern)
            for key, value in instance.items():
                if key in properties:
                    continue
                if regex.search(key):
                    errors.extend(
                        validate(value, sub_schema, f"{path}.{key}" if path else key)
                    )

    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))

    return errors


def validate_config(
    config: Dict[str, Any], schema: Dict[str, Any]
) -> List[Dict[str, str]]:
    """Validate a full Auto Lights config document against the config schema."""
    return validate(config, schema)
