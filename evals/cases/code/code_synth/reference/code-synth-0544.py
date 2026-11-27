# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('e', 'i')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s.swapcase()
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
