# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('e', 'n')
    s = s[:9].ljust(9, '.')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.lower()
    s = s[:7].ljust(7, '.')
    s = ''.join(sorted(s))
    s = s[:6].ljust(6, '.')
    s = ' '.join(s.split()[:2])
    s = ''.join(dict.fromkeys(s))
    s = s[:9].ljust(9, '.')
    s = ''.join(sorted(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(dict.fromkeys(s))
    s = s.lower()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w.capitalize() for w in s.split())
    return len(s)
