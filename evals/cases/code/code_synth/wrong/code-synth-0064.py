# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ' '.join(s.split())
    s = s.upper()
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:7].ljust(7, '.')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = ' '.join(s.split()[:4])
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    return s
