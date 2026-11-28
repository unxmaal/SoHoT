# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(sorted(s))
    s = s.swapcase()
    s = s.replace('e', 'l')
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('t', 's')
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split()[:2])
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return s
