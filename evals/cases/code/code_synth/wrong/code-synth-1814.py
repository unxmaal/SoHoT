# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = s.replace('i', 't')
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 3) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.lower()
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = s[:8].ljust(8, '.')
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.replace('d', 'r')
    s = ''.join(sorted(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
