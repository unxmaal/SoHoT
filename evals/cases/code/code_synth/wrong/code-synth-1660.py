# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def compute(s):
    s = ''.join(sorted(s))
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ''.join(chr((ord(c) - ord('a' if c.islower() else 'A') + 2) % 26 + ord('a' if c.islower() else 'A')) if c.isascii() and c.isalpha() else c for c in s)
    s = s.lower()
    s = ''.join(sorted(s))
    s = s.upper()
    s = ' '.join(s.split())
    s = s.replace('a', 's')
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = s.replace('r', 'l')
    s = ' '.join(s.split())
    import re
    s = re.sub(r'\d+', lambda m: str(len(m.group())), s)
    s = ' '.join(s.split())
    s = s[:7].ljust(7, '.')
    s = s.upper()
    s = ''.join(dict.fromkeys(s))
    s = ' '.join(w[::-1] for w in s.split())
    s = ''.join(c for c in s if c.lower() not in 'aeiou')
    return len(s)
