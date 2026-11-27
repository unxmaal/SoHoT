# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    s = s.lower()
    s = ''.join(sorted(s))
    w = s.split()
    return max(w, key=len) if w else ''
