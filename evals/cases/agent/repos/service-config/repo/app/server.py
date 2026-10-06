import configparser
import os


def load(env=None):
    env = env or os.environ.get("APP_ENV", "base")
    cfg = configparser.ConfigParser()
    cfg.read(["config/base.ini", f"config/{env}.ini"])
    return cfg


def port(env=None):
    return load(env).getint("server", "port")
