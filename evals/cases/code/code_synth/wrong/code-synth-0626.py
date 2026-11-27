# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(s):
    s = ''.join(dict.fromkeys(s))
    s = s.replace('n', 'l')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('o', 'd')
    w = s.split()
    return max(w, key=len) if w else ''
