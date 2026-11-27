# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = s.lower()
    s = ' '.join(w.capitalize() for w in s.split())
    import itertools
    s = ''.join(str(len(list(g))) + k for k, g in itertools.groupby(s))
    s = ''.join(dict.fromkeys(s))
    s = s.upper()
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    w = s.split()
    return max(w, key=len) if w else ''
