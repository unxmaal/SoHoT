# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def process(s):
    s = ' '.join(s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('c', 'r')
    s = ' '.join(s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.replace('r', 't')
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split()[:3])
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
