"""Catalog helpers."""
import re
from granary import pricing


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def quay_view(value, edges):
    """One quay view for the catalog page."""
    return {'quay_view': pricing.bucket(value, edges)}
