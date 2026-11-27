# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def apply_rules(xs):
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x % 7 != 0]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = xs[::-1]
    xs = [x + 9 for x in xs]
    xs = [x for x in xs if x > -1]
    xs = [x % 5 for x in xs]
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
