import json
from datetime import datetime

type JsonCompatible = (
    None
    | bool
    | int
    | float
    | str
    | datetime
    | set[JsonCompatible]
    | list[JsonCompatible]
    | dict[str, JsonCompatible]
)


class JsonCompatibleEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return {"__type__": "datetime", "value": o.isoformat()}
        elif isinstance(o, set):
            return {"__type__": "set", "value": list(o)}

        return super().default(o)


def _object_hook(obj):
    marker = obj.get("__type__")
    if marker == "datetime":
        return datetime.fromisoformat(obj["value"])
    elif marker == "set":
        return set(obj["value"])

    return obj


def dump_json_compatible(data: JsonCompatible) -> str:
    return json.dumps(data, cls=JsonCompatibleEncoder)


def load_json_compatible(data: str) -> JsonCompatible:
    return json.loads(data, object_hook=_object_hook)
