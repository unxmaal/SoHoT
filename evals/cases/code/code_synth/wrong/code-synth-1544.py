# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ' '.join(s.split())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 5) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(sorted(s))
    s = s.swapcase()
    s = s.upper()
    s = ''.join(sorted(s))
    s = ' '.join(s.split()[:2])
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.replace('e', 'o')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    return s
