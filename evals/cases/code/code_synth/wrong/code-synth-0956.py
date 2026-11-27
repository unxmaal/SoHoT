# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    s = ' '.join(s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.replace('r', 'i')
    s = ''.join(dict.fromkeys(s))
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
