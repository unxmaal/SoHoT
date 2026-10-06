"""Parsing helpers for settings read from the environment."""

TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off"}


def parse_bool(value):
    """'yes' -> True, 'off' -> False; anything else raises ValueError."""
    v = str(value).strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    raise ValueError(f"not a boolean: {value!r}")


def parse_int(value, default=None):
    if value is None or str(value).strip() == "":
        return default
    return int(value)
