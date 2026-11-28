# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def run_pipeline(xs):
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = [min(5, max(-3, x)) for x in xs]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [sum(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = list(dict.fromkeys(xs))
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = [x for x in xs if x > 8]
    xs = xs[::2]
    xs = sorted(xs)
    xs = [x * x for x in xs]
    xs = [x for x in xs if x % 2 == 0]
    xs = [max(xs[max(0, i - 2):i + 1]) for i in range(len(xs))]
    return len(set(xs))
