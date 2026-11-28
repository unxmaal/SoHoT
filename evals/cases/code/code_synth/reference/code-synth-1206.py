# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def compute(s):
    s = ' '.join(s.split()[:3])
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(s.split()[:4])
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
