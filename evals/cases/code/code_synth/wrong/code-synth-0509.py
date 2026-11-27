# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s[:7].ljust(7, '.')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.lower()
    s = s.upper()
    s = ''.join(sorted(s))
    s = ''.join(dict.fromkeys(s))
    w = s.split()
    return max(w, key=len) if w else ''
