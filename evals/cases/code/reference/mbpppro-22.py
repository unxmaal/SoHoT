# Imported by evals/benchmark_import.py from hf:CodeEval-Pro/mbpp-pro@50f18448e09a8383226e1a5cd3654d2a454fe333, item 22.
# Write a function to sort a list of tuples using the second value of each tuple.
def subject_marks(subjectmarks):
#subject_marks = [('English', 88), ('Science', 90), ('Maths', 97), ('Social sciences', 82)])
 subjectmarks.sort(key = lambda x: x[1])
 return subjectmarks


# Given a list of students' records, where each record is a list of tuples representing the student's name and their scores in different subjects, write a function to sort the records by the total score of each student in descending order. If two students have the same total score, sort them by their names in ascending order.
def sort_students_by_total_score(students):
    students.sort(key=lambda student: (-sum(score for _, score in student), student[0][0]))
    return students
