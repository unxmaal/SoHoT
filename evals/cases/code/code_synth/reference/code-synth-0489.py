# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split()[:2])
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = s[:7].ljust(7, '.')
    s = ''.join(sorted(s))
    s = ' '.join(s.split())
    s = s.swapcase()
    w = s.split()
    return max(w, key=len) if w else ''
