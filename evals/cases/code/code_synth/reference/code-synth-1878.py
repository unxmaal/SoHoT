# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('s', 'e')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if not c.isdigit())
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split()[:3])
    s = s.replace('t', 'b')
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('a', 'e')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
