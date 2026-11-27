# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ' '.join(s.split()[:2])
    s = ' '.join(w.capitalize() for w in s.split())
    return s
