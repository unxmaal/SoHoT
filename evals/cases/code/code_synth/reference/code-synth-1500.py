# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = s[:6].ljust(6, '.')
    s = ''.join(sorted(s))
    s = ' '.join(s.split())
    s = ' '.join(s.split()[:3])
    s = s.lower()
    s = s.replace('n', 'e')
    s = s.swapcase()
    s = ''.join(dict.fromkeys(s))
    s = s[:8].ljust(8, '.')
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split()[:4])
    s = s.upper()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 8) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(sorted(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(w.capitalize() for w in s.split())
    w = s.split()
    return max(w, key=len) if w else ''
