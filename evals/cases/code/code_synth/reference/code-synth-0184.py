# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(sorted(s))
    s = ' '.join(w.capitalize() for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    return s
