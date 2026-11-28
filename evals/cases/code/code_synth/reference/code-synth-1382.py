# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = s[:9].ljust(9, '.')
    s = s.replace('d', 't')
    s = ''.join(dict.fromkeys(s))
    s = s.swapcase()
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(reversed(s.split()))
    s = s[:8].ljust(8, '.')
    s = s.upper()
    s = s[:5].ljust(5, '.')
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('c', 'n')
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
