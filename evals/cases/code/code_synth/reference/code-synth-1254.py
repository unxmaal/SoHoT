# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:7].ljust(7, '.')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = ' '.join(reversed(s.split()))
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = s.replace('i', 'l')
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:4])
    s = ''.join(sorted(s))
    s = s.replace('r', 'i')
    w = s.split()
    return max(w, key=len) if w else ''
