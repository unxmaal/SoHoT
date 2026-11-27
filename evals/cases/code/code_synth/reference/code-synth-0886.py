# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def apply_rules(s):
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ' '.join(s.split()[:4])
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    w = s.split()
    return max(w, key=len) if w else ''
