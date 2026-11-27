# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = s.replace('c', 'b')
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
