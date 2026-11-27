# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = s[:5].ljust(5, '.')
    s = ' '.join(s.split()[:2])
    s = ' '.join(w[::-1] for w in s.split())
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(reversed(s.split()))
    w = s.split()
    return max(w, key=len) if w else ''
