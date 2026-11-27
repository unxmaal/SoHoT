# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def transform(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w[::-1] for w in s.split())
    s = s.lower()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 4) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    return len(s)
