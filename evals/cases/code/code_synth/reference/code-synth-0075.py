# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603@9a8082722465612b071875da7b79985eb7025c9a.
def count_bits(lo, hi):
    return sum(1 for x in range(lo, hi + 1) if bin(x).count('1') == 1)
