# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:8].ljust(8, '.')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = s.lower()
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('s', 'i')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    return s
