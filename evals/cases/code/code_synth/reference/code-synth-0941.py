# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def transform(s):
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = s.upper()
    s = ' '.join(reversed(s.split()))
    w = s.split()
    return max(w, key=len) if w else ''
