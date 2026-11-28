# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.upper()
    s = ' '.join(s.split())
    s = s[:6].ljust(6, '.')
    s = ' '.join(s.split())
    s = ' '.join(s.split()[:4])
    s = ''.join(sorted(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 8) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s[:8].ljust(8, '.')
    s = ' '.join(s.split()[:4])
    w = s.split()
    return max(w, key=len) if w else ''
