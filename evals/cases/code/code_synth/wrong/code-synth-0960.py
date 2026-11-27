# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return len(s)
