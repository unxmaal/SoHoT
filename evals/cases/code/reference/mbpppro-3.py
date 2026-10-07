# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 3.
# Write a python function to check whether the two numbers differ at one bit position only or not.
def is_Power_Of_Two(x: int): 
    return x > 0 and (x & (x - 1)) == 0
def differ_At_One_Bit_Pos(a: int,b: int):
    return is_Power_Of_Two(a ^ b)


# Given a list of integers, find the number of pairs of integers in the list that differ at exactly one bit position. For example, in the list [1, 2, 3, 4], the pairs (1, 2), (1, 4), and (2, 3) differ at exactly one bit position.
def count_pairs_differ_at_one_bit_pos(nums):
    count = 0
    n = len(nums)
    
    # Check all pairs of integers in the list
    for i in range(n):
        for j in range(i + 1, n):
            if differ_At_One_Bit_Pos(nums[i], nums[j]):
                count += 1
                
    return count
