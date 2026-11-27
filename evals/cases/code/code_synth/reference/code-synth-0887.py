# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ' '.join(reversed(s.split()))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split()[:3])
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    s = ' '.join(s.split()[:2])
    return len(s.split())
