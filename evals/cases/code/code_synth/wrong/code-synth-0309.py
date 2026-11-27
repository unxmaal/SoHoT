# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def reduce_data(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = ''.join(dict.fromkeys(s))
    s = s.replace('s', 'l')
    s = s[:9].ljust(9, '.')
    s = s.lower()
    s = s.replace('b', 'e')
    s = s.swapcase()
    return len(s)
