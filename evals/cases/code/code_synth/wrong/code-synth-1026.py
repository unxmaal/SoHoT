# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = ''.join(sorted(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 11) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.replace('b', 'a')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(sorted(s))
    s = s.swapcase()
    return s
