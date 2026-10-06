"""Till receipts."""


from shop.money import format_cents


def receipt(lines):
    total = sum(c for _, c in lines)
    body = [f"{n:<12}{format_cents(c):>12}" for n, c in lines]
    return "\n".join(body + [f"{'TOTAL':<12}{format_cents(total):>12}"])
