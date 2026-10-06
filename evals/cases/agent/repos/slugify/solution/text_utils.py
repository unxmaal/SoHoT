"""Small text helpers used across the CMS."""


def truncate(text, width):
    """Cut text to width characters, ending in '...' when cut."""
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def slugify(title):
    """Turn a title into a URL slug.

    Lower-case; every run of characters that are not ASCII letters or
    digits becomes a single '-'; no leading or trailing '-'.
    'Hello, World!' -> 'hello-world'; '  A  B  ' -> 'a-b'; '' -> ''.
    """
    import re
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
