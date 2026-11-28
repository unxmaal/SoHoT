# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def process(xs):
    xs = [int(x / 2) for x in xs]
    xs = sorted(xs, reverse=True)
    xs = xs[::-1]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = [x for x in xs if x % 2 != 0]
    xs = sorted(xs, reverse=True)
    xs = [max(xs[:i + 1]) for i in range(len(xs))]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = [int(x / 2) for x in xs]
    xs = [abs(x) for x in xs]
    xs = [sum(xs[i:i + 2]) for i in range(0, len(xs), 2)]
    xs = list(dict.fromkeys(reversed(xs)))[::-1]
    xs = sorted(xs, key=abs)
    return sum(xs)
