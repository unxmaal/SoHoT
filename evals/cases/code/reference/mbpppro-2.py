# Write a function to find the n largest integers from a given list of numbers, returned in descending order.
import heapq as hq
def heap_queue_largest(nums: list,n: int) -> list:
  largest_nums = hq.nlargest(n, nums)
  return largest_nums


# Given a list of lists, where each sublist contains integers, write a function to find the n largest integers from each sublist and return them in a single list, sorted in descending order.
def find_n_largest_from_lists(lists: list, n: int) -> list:
    result = []
    for sublist in lists:
        # Find the n largest numbers in the current sublist
        largest_from_sublist = heap_queue_largest(sublist, n)
        result.extend(largest_from_sublist)  # Add them to the result list
    
    # Sort the final result in descending order
    result.sort(reverse=True)
    return result
