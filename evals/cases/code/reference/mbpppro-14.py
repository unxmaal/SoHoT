# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 14.
# Write a function to check if the given number is woodball or not.
def is_woodall(x):
    if not isinstance(x, int):
        return False
    if x <= 0 or x % 2 == 0:
        return False
    if (x == 1): 
        return True
    x += 1 
    i = 0
    while (x % 2 == 0): 
        x /= 2
        i += 1
        if (i == x): 
            return True
    return False


# Write a function to find the first 10 woodall numbers in a given range of integers. A woodall number is defined as a number of the form W(n) = n * 2^n - 1. The function should return a list of the first 10 woodall numbers found within the given range, or an empty list if no such numbers exist within the range.
def find_first_10_woodall_numbers(start, end): 
    woodall_numbers = []
    for x in range(start, end + 1):
        if is_woodall(x):
            woodall_numbers.append(x)
            if len(woodall_numbers) == 10:
                break
    return woodall_numbers
