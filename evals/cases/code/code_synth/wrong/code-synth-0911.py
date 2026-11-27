# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def solve(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 7) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('o', 'e')
    s = s[:8].ljust(8, '.')
    w = s.split()
    return max(w, key=len) if w else ''
