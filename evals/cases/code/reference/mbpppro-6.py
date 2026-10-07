# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 6.
# Write a python function to find the minimum number of rotations (greater than 0) required to get the same string.
def find_Rotations(s):
    n = len(s)
    s += s
    for i in range(1, n + 1):
        if s[i: i + n] == s[0: n]:
            return i
    return n


# Given a list of strings, write a Python function to find the minimum number of rotations required to get the same string for each string in the list. The function should return a list of integers where each integer represents the minimum number of rotations required for the corresponding string in the input list.
def find_Rotations_for_list(strings):
    def find_Rotations(s):
        n = len(s)
        s += s
        for i in range(1, n + 1):
            if s[i: i + n] == s[0: n]:
                return i
        return n
    return [find_Rotations(s) for s in strings]
