# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.replace('b', 'c')
    s = ' '.join(s.split()[:3])
    s = ' '.join(s.split())
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
