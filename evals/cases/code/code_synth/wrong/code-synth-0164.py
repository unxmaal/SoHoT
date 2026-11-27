# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = s.lower()
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 7) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(s.split()[:2])
    s = s.upper()
    s = s.swapcase()
    s = s.replace('o', 'a')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
