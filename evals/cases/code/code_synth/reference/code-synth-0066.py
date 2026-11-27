# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ' '.join(s.split())
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:3])
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    return len(s)
