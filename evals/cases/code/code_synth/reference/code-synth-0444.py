# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ''.join(sorted(s))
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split()[:3])
    s = s[:7].ljust(7, '.')
    s = ' '.join(s.split())
    s = s.lower()
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
