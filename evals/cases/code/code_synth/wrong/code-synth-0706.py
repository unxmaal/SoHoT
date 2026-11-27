# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = s.replace('t', 'n')
    s = ' '.join(reversed(s.split()))
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = ' '.join(reversed(s.split()))
    return len(s.split())
