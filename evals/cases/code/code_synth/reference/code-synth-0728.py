# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = s[:5].ljust(5, '.')
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.swapcase()
    s = ' '.join(s.split()[:4])
    s = ''.join(sorted(s))
    return s
