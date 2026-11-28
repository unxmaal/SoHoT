# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:9].ljust(9, '.')
    s = ' '.join(s.split()[:2])
    s = ''.join(sorted(s))
    s = s.swapcase()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.lower()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split()[:4])
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.upper()
    s = ' '.join(w.capitalize() for w in s.split())
    return len(s)
