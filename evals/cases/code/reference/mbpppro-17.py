# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 17.
# Write a python function to check whether the given two integers have opposite sign or not.
def opposite_Signs(x,y):
    return ((x ^ y) < 0)


# Given a list of tuples, where each tuple contains two integers, write a Python function to count the number of tuples where the integers have opposite signs.
def count_Opposite_Signs(tuples_list):
    count = 0
    for x, y in tuples_list:
        if opposite_Signs(x, y):
            count += 1
    return count
