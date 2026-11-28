# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ' '.join(s.split()[:4])
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split()[:3])
    s = s.replace('r', 'a')
    s = s[:9].ljust(9, '.')
    s = ''.join(dict.fromkeys(s))
    s = s.lower()
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.lower()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 11) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.replace('o', 'b')
    s = ''.join(c for c in s if not c.isdigit())
    w = s.split()
    return max(w, key=len) if w else ''
