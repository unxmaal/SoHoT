# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = s.replace('b', 'r')
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(dict.fromkeys(s))
    s = s.lower()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ''.join(sorted(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    s = s.replace('e', 't')
    w = s.split()
    return max(w, key=len) if w else ''
