# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(s):
    s = s.replace('b', 'd')
    s = ' '.join(w[::-1] for w in s.split())
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 4) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    w = s.split()
    return max(w, key=len) if w else ''
