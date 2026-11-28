# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = s.swapcase()
    s = ' '.join(w.capitalize() for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.replace('s', 'n')
    s = s[:6].ljust(6, '.')
    s = s.replace('c', 'o')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split())
    s = s.swapcase()
    s = ' '.join(w[::-1] for w in s.split())
    s = s.upper()
    s = s[:6].ljust(6, '.')
    s = s.upper()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 6) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.replace('o', 'n')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    return s
