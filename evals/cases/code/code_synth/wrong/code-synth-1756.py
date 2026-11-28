# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 6) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.replace('n', 'l')
    s = s.swapcase()
    s = s.replace('r', 'l')
    s = s.swapcase()
    s = s.replace('d', 'a')
    s = s[:7].ljust(7, '.')
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split()[:3])
    s = s.upper()
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    w = s.split()
    return max(w, key=len) if w else ''
