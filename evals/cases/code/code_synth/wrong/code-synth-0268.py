# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ' '.join(s.split()[:2])
    return s
