# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('l', 'd')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = s.upper()
    s = s.lower()
    s = ''.join(sorted(s))
    s = ' '.join(s.split()[:2])
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
