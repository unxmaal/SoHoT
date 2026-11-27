# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(s):
    s = s[:6].ljust(6, '.')
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 11) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
