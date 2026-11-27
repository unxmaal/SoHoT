# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [abs(x) for x in xs]
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[1:]
    xs = [x * 5 for x in xs]
    xs = [x for x in xs if x % 4 != 0]
    xs = xs[::-1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = sorted(xs)
    if xs:
        k = 6 % len(xs)
        xs = xs[k:] + xs[:k]
    return len(set(xs))
