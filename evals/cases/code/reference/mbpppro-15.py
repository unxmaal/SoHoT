# Write a python function to check if a given number is one less than twice its reverse.
def check(n):
    return n == 2 * int(str(n)[::-1]) - 1


# Write a Python function to find all numbers within a given range that are one less than twice their reverse. The function should return a list of all such numbers.
def find_numbers_in_range(start, end):
    result = []
    for n in range(start, end + 1):
        if check(n):
            result.append(n)
    return result
