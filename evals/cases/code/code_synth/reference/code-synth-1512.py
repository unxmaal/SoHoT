# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 10) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.swapcase()
    s = s.upper()
    s = s.replace('o', 'i')
    s = s.upper()
    s = ''.join(sorted(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split()[:2])
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w.capitalize() for w in s.split())
    s = s[:8].ljust(8, '.')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
