"""Service settings: config/base.ini, then config/<env>.ini over it, then OVERRIDES."""
import configparser
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Values pinned in code; they win over the ini files.
OVERRIDES = {
    'development': {'port': '31359', 'workers': '14'},
    'staging': {'workers': '28'},
}


def load(env=None):
    env = env or os.environ.get("APP_ENV", "development")
    parser = configparser.ConfigParser()
    parser.read([ROOT / "config" / "base.ini", ROOT / "config" / f"{env}.ini"])
    values = dict(parser["service"])
    values.update(OVERRIDES.get(env, {}))
    return values
