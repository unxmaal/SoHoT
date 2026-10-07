# Write a python function to count the number of substrings with the sum of digits equal to their length.
from collections import defaultdict
def count_Substrings(s):
    n, count, sum = len(s), 0, 0
    mp = defaultdict(lambda : 0)
    mp[0] += 1
    for i in range(n):
        sum += ord(s[i]) - ord('0')
        count += mp[sum - i - 1]
        mp[sum - i - 1] += 1
    return count


# Given a list of strings, write a Python function to count the total number of substrings across all strings where the sum of the digits of the substring equals the length of the substring. The function should return the total count of such substrings.
from collections import defaultdict

def count_Substrings(s):
    n, count, sum = len(s), 0, 0
    mp = defaultdict(lambda : 0)
    mp[0] += 1
    for i in range(n):
        sum += ord(s[i]) - ord('0')
        count += mp[sum - i - 1]
        mp[sum - i - 1] += 1
    return count

def total_count_Substrings(strings):
    total_count = 0
    for s in strings:
        total_count += count_Substrings(s)
    return total_count
