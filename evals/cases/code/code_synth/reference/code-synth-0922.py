# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = s[:6].ljust(6, '.')
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(sorted(s))
    s = s.swapcase()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 3) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    return len(s)
