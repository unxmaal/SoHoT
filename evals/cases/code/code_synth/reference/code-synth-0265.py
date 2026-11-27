# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def reduce_data(s):
    s = ''.join(dict.fromkeys(s))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    s = s.replace('l', 'b')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.lower()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.swapcase()
    w = s.split()
    return max(w, key=len) if w else ''
