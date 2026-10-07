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
