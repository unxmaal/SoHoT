def normalize_sku(raw):
    """Upper-case, strip, and drop dashes: ' ab-12 ' -> 'AB12'."""
    return raw.strip().upper().replace("-", "")


def is_valid(raw):
    sku = normalize_sku(raw)
    return sku.isalnum() and 4 <= len(sku) <= 12
