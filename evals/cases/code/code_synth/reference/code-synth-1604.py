# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ' '.join(reversed(s.split()))
    s = s[:6].ljust(6, '.')
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    s = s.replace('e', 'n')
    s = ' '.join(s.split())
    s = s.replace('e', 'b')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    return len(s)
