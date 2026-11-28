# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def run_pipeline(s):
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = s.swapcase()
    s = ' '.join(s.split()[:3])
    s = ' '.join(reversed(s.split()))
    s = ''.join(sorted(s))
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ''.join(sorted(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = s.lower()
    s = ''.join(c for c in s if not c.isdigit())
    s = ' '.join(s.split())
    s = s.swapcase()
    s = ''.join(sorted(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    w = s.split()
    return max(w, key=len) if w else ''
