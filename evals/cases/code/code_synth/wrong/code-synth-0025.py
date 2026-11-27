# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ''.join(sorted(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 8) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.lower()
    s = ' '.join(reversed(s.split()))
    w = s.split()
    return max(w, key=len) if w else ''
