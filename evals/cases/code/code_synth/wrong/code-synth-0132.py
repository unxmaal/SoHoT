# Imported by evals/importers from generated:evals.importers.code_synth v1 seed 603: a deliberately wrong answer, never graded.
def count_bits(lo, hi):
    from math import comb
    if hi < lo:
        return 0
    def upto(m):
        if m < 0:
            return 0
        bits, ones, res = bin(m)[2:], 0, 0
        for i, b in enumerate(bits):
            if b == '1':
                rem, need = len(bits) - i - 1, 5 - ones
                if 0 <= need <= rem:
                    res += comb(rem, need)
                ones += 1
        return res + (ones == 5)
    return upto(hi) - upto(lo - 1)
