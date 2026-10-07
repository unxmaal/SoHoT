# Write a function to flatten a list and sum all of its elements.
def recursive_list_sum(data_list):
    total = 0
    for element in data_list:
        if type(element) == type([]):
            total = total + recursive_list_sum(element)
        else:
            total = total + element
    return total


# Given a list of lists, where each sublist contains either integers or nested sublists, write a function to flatten each sublist and then sum the elements of all the flattened sublists.
def sum_of_flattened_lists(list_of_lists):
    total_sum = 0
    for sublist in list_of_lists:
        total_sum += recursive_list_sum(sublist)
    return total_sum
