# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w.capitalize() for w in s.split())
    s = s[:8].ljust(8, '.')
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    s = s.replace('l', 'd')
    s = s[:9].ljust(9, '.')
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.swapcase()
    s = s.replace('o', 't')
    return s
