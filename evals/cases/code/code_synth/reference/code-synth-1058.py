# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def solve(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.lower()
    s = ''.join(sorted(s))
    s = ' '.join(w.capitalize() for w in s.split())
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(sorted(s))
    s = s.lower()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(reversed(s.split()))
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.upper()
    s = ' '.join(s.split())
    return min(set(s), key=lambda c: (-s.count(c), c)) if s else ''
