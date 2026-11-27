# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ''.join(sorted(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 9) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(w.capitalize() for w in s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split()[:4])
    return s
