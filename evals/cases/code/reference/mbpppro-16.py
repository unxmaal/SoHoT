# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 16.
# Write a python function to find the largest number that can be formed with the given list of digits.
def find_Max_Num(arr):
    arr.sort(reverse = True)
    return int("".join(map(str,arr)))


# Given a list of lists of digits, write a Python function to find the largest number that can be formed by concatenating the largest number from each list of digits.
def find_Max_Num_From_Lists(lists):
    return int(''.join(str(find_Max_Num(lst)) for lst in lists))
