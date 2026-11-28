# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = s.swapcase()
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('l', 'c')
    s = s[:6].ljust(6, '.')
    s = ''.join(c for c in s if not c.isdigit())
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.lower()
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    return s
