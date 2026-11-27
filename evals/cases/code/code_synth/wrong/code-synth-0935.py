# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ' '.join(s.split()[:3])
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s[:5].ljust(5, '.')
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(dict.fromkeys(s))
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
