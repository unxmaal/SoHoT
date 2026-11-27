# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(s):
    s = s.swapcase()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 6) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(s.split()[:4])
    s = ''.join(sorted(s))
    s = s[:9].ljust(9, '.')
    s = s.lower()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(c for c in s if not c.isdigit())
    w = s.split()
    return max(w, key=len) if w else ''
