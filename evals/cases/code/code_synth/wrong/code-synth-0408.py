# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = s.replace('l', 'c')
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    s = ' '.join(s.split()[:2])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = ' '.join(s.split())
    return s
