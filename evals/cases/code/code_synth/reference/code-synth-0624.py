# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ' '.join(s.split()[:2])
    s = s[:6].ljust(6, '.')
    s = s.replace('s', 'c')
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(sorted(s))
    s = ' '.join(s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
