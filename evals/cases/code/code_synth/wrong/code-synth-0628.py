# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 3) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = s.swapcase()
    s = ''.join(dict.fromkeys(s))
    s = s.replace('a', 'b')
    s = s.upper()
    s = s.swapcase()
    return len(s)
