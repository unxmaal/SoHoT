# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    s = s.replace('l', 'd')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(w[::-1] for w in s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = s.replace('a', 's')
    s = ' '.join(s.split()[:3])
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.replace('s', 'c')
    s = s[:7].ljust(7, '.')
    s = s.lower()
    s = ''.join(sorted(s))
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
