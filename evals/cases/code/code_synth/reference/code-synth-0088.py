# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(dict.fromkeys(s))
    s = s.lower()
    s = s.replace('t', 'i')
    s = ' '.join(reversed(s.split()))
    w = s.split()
    return max(w, key=len) if w else ''
