# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ' '.join(s.split()[:4])
    s = ' '.join(reversed(s.split()))
    s = ''.join(dict.fromkeys(s))
    s = s.replace('b', 'l')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.replace('d', 'r')
    s = s.swapcase()
    s = s.upper()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.lower()
    s = ' '.join(s.split()[:4])
    w = s.split()
    return max(w, key=len) if w else ''
