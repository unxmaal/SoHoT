# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = list(dict.fromkeys(xs))
    xs = [v for i in range(0, len(xs), 2) for v in reversed(xs[i:i + 2])]
    xs = [x for x in xs if x > 4]
    xs = xs[::-1]
    xs = [x for x in xs if x % 7 != 0]
    xs = sorted(xs)
    xs = [x for x in xs if x > 5]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, key=abs)
    xs = xs[:5]
    xs = [int(x / 3) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [x for x in xs if x % 2 == 0]
    xs = sorted(xs, reverse=True)
    d = sorted(set(xs))
    return d[-2] if len(d) > 1 else None
