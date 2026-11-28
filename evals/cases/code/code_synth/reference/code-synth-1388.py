# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = ' '.join(s.split()[:3])
    s = s.swapcase()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.upper()
    s = s.replace('n', 't')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w[::-1] for w in s.split())
    s = s.swapcase()
    s = s.replace('b', 'c')
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(sorted(s))
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
