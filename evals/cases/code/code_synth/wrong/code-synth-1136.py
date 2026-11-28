# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(s):
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.swapcase()
    s = ' '.join(reversed(s.split()))
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(s.split())
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    s = s.replace('n', 'r')
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 8) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s[:5].ljust(5, '.')
    s = ''.join(c for i, c in enumerate(s) if i == 0 or c != s[i - 1])
    s = ' '.join(reversed(s.split()))
    s = ' '.join(s.split())
    s = ' '.join(w.capitalize() for w in s.split())
    s = s.upper()
    s = s[:6].ljust(6, '.')
    s = s.lower()
    return s
