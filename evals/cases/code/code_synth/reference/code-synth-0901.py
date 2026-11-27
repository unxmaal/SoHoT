# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = s.swapcase()
    s = s.upper()
    s = s.lower()
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ''.join(sorted(s))
    s = s[:8].ljust(8, '.')
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:5].ljust(5, '.')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
