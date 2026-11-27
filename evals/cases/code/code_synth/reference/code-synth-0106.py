# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(s.split())
    s = ' '.join(s.split()[:3])
    s = s.upper()
    s = s[:6].ljust(6, '.')
    s = ' '.join(s.split()[:3])
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    s = ''.join(sorted(s))
    w = s.split()
    return max(w, key=len) if w else ''
