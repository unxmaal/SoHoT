# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(w[::-1] for w in s.split())
    s = s.replace('l', 't')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = s.replace('a', 's')
    s = ' '.join(reversed(s.split()))
    s = s[:5].ljust(5, '.')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    s = ''.join(sorted(s))
    s = s.upper()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = ' '.join(reversed(s.split()))
    s = s.swapcase()
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    w = s.split()
    return max(w, key=len) if w else ''
