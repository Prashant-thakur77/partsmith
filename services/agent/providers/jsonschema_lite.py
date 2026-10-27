"""Small JSON Schema subset: validate model replies and build minimal schema-valid mock answers.

Covers what strict structured output allows (type, properties, required, additionalProperties, items, enum,
const, numeric/length/count bounds, pattern, anyOf/oneOf/allOf, local `$ref`). No dependency beyond stdlib.
"""

from __future__ import annotations

import json
import re
from typing import Any

Schema = dict[str, Any]

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


def _resolve(schema: Schema, root: Schema) -> Schema:
    seen = 0
    while "$ref" in schema and seen < 32:
        ref = str(schema["$ref"])
        if not ref.startswith("#/"):
            raise ValueError(f"only local $ref is supported, got {ref!r}")
        node: Any = root
        for part in ref[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        schema = node
        seen += 1
    return schema


def _is_type(value: Any, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    if name == "integer" and isinstance(value, float):
        return value.is_integer()
    return isinstance(value, _TYPES.get(name, (object,)))


def validate(instance: Any, schema: Schema, root: Schema | None = None, path: str = "$") -> list[str]:
    """Return a list of human-readable errors (empty = valid)."""
    root = root if root is not None else schema
    schema = _resolve(schema, root)
    errors: list[str] = []
    if "allOf" in schema:
        for sub in schema["allOf"]:
            errors += validate(instance, sub, root, path)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            matches = sum(1 for sub in schema[key] if not validate(instance, sub, root, path))
            if matches == 0 or (key == "oneOf" and matches > 1):
                errors.append(f"{path}: does not match {key}")
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']!r}")
    t = schema.get("type")
    if t is not None:
        names = t if isinstance(t, list) else [t]
        if not any(_is_type(instance, n) for n in names):
            errors.append(f"{path}: expected {'|'.join(names)}, got {type(instance).__name__}")
            return errors
    if isinstance(instance, dict):
        props: dict[str, Any] = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required {req!r}")
        extra = schema.get("additionalProperties", True)
        for k, v in instance.items():
            if k in props:
                errors += validate(v, props[k], root, f"{path}.{k}")
            elif extra is False:
                errors.append(f"{path}: unexpected property {k!r}")
            elif isinstance(extra, dict):
                errors += validate(v, extra, root, f"{path}.{k}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(instance):
                errors += validate(item, schema["items"], root, f"{path}[{i}]")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: {instance} <= exclusiveMinimum {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: {instance} >= exclusiveMaximum {schema['exclusiveMaximum']}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    return errors


def minimal_instance(schema: Schema, root: Schema | None = None, label: str = "mock") -> Any:
    """Smallest value that satisfies `schema`; strings carry `label` so mock output is recognisable."""
    root = root if root is not None else schema
    schema = _resolve(schema, root)
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            options = [_resolve(o, root) for o in schema[key]]
            non_null = [o for o in options if o.get("type") != "null"]
            return minimal_instance((non_null or options)[0], root, label)
    if schema.get("allOf"):
        merged: Schema = {}
        for sub in schema["allOf"]:
            merged.update(_resolve(sub, root))
        return minimal_instance(merged, root, label)
    t = schema.get("type")
    if isinstance(t, list):
        non_null_types = [x for x in t if x != "null"]
        t = non_null_types[0] if non_null_types else "null"
    if t is None:
        t = "object" if "properties" in schema else "string"
    if t == "object":
        props: dict[str, Any] = schema.get("properties", {})
        return {k: minimal_instance(props.get(k, {}), root, label) for k in schema.get("required", [])}
    if t == "array":
        item_schema = schema.get("items", {})
        return [minimal_instance(item_schema, root, label) for _ in range(int(schema.get("minItems", 0)))]
    if t in ("number", "integer"):
        lo = schema.get("minimum", schema.get("exclusiveMinimum"))
        hi = schema.get("maximum", schema.get("exclusiveMaximum"))
        value: float = 0
        if lo is not None:
            value = lo + (1 if "exclusiveMinimum" in schema and "minimum" not in schema else 0)
        elif hi is not None and hi < 0:
            value = hi
        return int(value) if t == "integer" else float(value)
    if t == "boolean":
        return False
    if t == "null":
        return None
    text = label
    min_len = int(schema.get("minLength", 0))
    if len(text) < min_len:
        text = text + "_" * (min_len - len(text))
    if "maxLength" in schema:
        text = text[: int(schema["maxLength"])]
    return text


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply: plain JSON, a fenced ```json block, or the outermost {...} / [...] span."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    for m in _FENCE_RE.finditer(stripped):
        try:
            return json.loads(m.group(1))
        except ValueError:
            continue
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = stripped.find(open_c), stripped.rfind(close_c)
        if 0 <= start < end:
            try:
                return json.loads(stripped[start : end + 1])
            except ValueError:
                continue
    raise ValueError("reply contains no parseable JSON")
