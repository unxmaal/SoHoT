# Write a function to find the shared elements from the given two lists.
def similar_elements(test_tup1, test_tup2):
  return tuple(set(test_tup1) & set(test_tup2))


# Given a list of lists, write a function to find the shared elements across all the lists.
def shared_elements(lists):
    if not lists:
        return ()
    
    # Start with the first list converted to a tuple
    shared = tuple(lists[0])
    
    # Iterate through the remaining lists
    for current_list in lists[1:]:
        shared = similar_elements(shared, tuple(current_list))
        # If at any point there are no shared elements, we can return early
        if not shared:
            return ()
    
    return shared
