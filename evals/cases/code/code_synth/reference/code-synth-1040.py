# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = s.upper()
    s = s.swapcase()
    s = ''.join(c for c in s if not c.isdigit())
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w[::-1] for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split()[:4])
    s = s.swapcase()
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(dict.fromkeys(s))
    return s
