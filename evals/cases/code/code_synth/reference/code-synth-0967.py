# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ' '.join(s.split()[:2])
    s = ' '.join(reversed(s.split()))
    s = s[:8].ljust(8, '.')
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    return s
