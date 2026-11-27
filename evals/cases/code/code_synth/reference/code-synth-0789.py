# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 11) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('s', 'a')
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s[:7].ljust(7, '.')
    s = s.replace('s', 'e')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
