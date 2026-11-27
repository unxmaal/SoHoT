# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = s[:9].ljust(9, '.')
    s = ' '.join(s.split()[:2])
    s = ' '.join(reversed(s.split()))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 6) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.replace('t', 'a')
    w = s.split()
    return max(w, key=len) if w else ''
