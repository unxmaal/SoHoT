# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:6].ljust(6, '.')
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = s.swapcase()
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 1) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    return s
