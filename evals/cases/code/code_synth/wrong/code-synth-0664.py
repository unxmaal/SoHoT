# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(s):
    s = ' '.join(s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('c', 'r')
    s = ' '.join(s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = s.replace('r', 't')
    s = ' '.join(s.split()[:3])
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
