# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = s[:8].ljust(8, '.')
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s[:9].ljust(9, '.')
    w = s.split()
    return max(w, key=len) if w else ''
