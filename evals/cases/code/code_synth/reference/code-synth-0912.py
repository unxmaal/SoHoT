# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = s[:7].ljust(7, '.')
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(sorted(s))
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.lower()
    s = ' '.join(s.split()[:4])
    w = s.split()
    return max(w, key=len) if w else ''
