# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = s.upper()
    s = s.replace('r', 't')
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 4) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(s.split())
    s = s.replace('a', 'e')
    s = s.upper()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 2) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.upper()
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = s.upper()
    s = s[:7].ljust(7, '.')
    s = ' '.join(s.split()[:3])
    return s
