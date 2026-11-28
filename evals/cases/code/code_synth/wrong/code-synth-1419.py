# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = list(dict.fromkeys(xs))
    xs = [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
    xs = [x for x in xs if x % 4 != 0]
    xs = [x for x in xs if x >= 0]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = xs[-2:]
    xs = sorted(xs, key=abs)
    xs = list(dict.fromkeys(xs))
    xs = [abs(x) for x in xs]
    xs = list(dict.fromkeys(xs))
    xs = [x // 4 for x in xs]
    xs = [min(9, max(0, x)) for x in xs]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
