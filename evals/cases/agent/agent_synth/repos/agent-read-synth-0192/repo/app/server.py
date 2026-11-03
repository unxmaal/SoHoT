"""Entry point."""
from app import settings


def main():
    values = settings.load()
    return int(values["port"]), int(values["workers"])
