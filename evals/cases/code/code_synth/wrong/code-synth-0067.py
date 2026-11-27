# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(s):
    s = s.upper()
    s = s.replace('o', 's')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ' '.join(s.split()[:4])
    s = ''.join(sorted(s))
    return len(s)
