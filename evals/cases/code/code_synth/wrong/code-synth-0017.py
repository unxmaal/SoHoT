# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def count_bits(lo, hi):
    return sum(1 for x in range(lo, hi + 1) if bin(x).count('1') >= 2)
