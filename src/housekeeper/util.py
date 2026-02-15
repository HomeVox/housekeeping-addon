import re

_split_re = re.compile(r"[^a-z0-9]+")


def tokenize(s: str) -> set[str]:
    s = (s or "").strip().lower()
    if not s:
        return set()
    return {t for t in _split_re.split(s) if t}


def is_suffix_duplicate_entity(entity_id: str) -> tuple[bool, str]:
    # sensor.foo_2 => (True, sensor.foo)
    m = re.match(r"^(?P<base>.+)_([2-9]|[1-9][0-9]+)$", entity_id)
    if not m:
        return (False, entity_id)
    return (True, m.group("base"))
