# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w[::-1] for w in s.split())
    s = s.lower()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
