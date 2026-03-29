# from app import app
# from models import db, Class, Subject, Teacher, TeachingAssignment, TimetableEntry
# from scheduler import DAYS, TIME_SLOTS
# from collections import defaultdict
# from input_processor import process_inputs, PARALLEL_DATA

# app.app_context().push()
# process_inputs()
# print("\n===== PARALLEL GROUP DEBUG (DETAILED) =====\n")

# def teacher_daily_load(teacher_id, day):
#     return TimetableEntry.query.filter_by(
#         teacher_id=teacher_id,
#         day=day
#     ).count()

# for cls in Class.query.all():

#     print(f"\nCLASS: {cls.name}")
#     print("-" * 50)

#     parallel_list = PARALLEL_DATA.get(cls.id, [])

#     if not parallel_list:
#         print("⚠️ No parallel data")
#         continue

#     # -----------------------------
#     # GROUP BY GROUP ID
#     # -----------------------------
#     parallel_groups = defaultdict(list)

#     for p in parallel_list:
#         group_id = p.get("group", 1)
#         parallel_groups[group_id].append(p)

#     # -----------------------------
#     # PROCESS EACH GROUP
#     # -----------------------------
#     for group_id, group in parallel_groups.items():

#         print(f"\n➡️ GROUP {group_id}")

#         subjects = []
#         teachers = []

#         # -----------------------------
#         # FETCH SUBJECT + TEACHER
#         # -----------------------------
#         for p in group:
#             subject_id = p["subject_id"]

#             subject = Subject.query.get(subject_id)

#             assignment = TeachingAssignment.query.filter_by(
#                 subject_id=subject_id,
#                 class_id=cls.id
#             ).first()

#             if not subject:
#                 print(f"❌ Subject NOT FOUND: {subject_id}")
#                 continue

#             if not assignment:
#                 print(f"❌ No teacher mapping for {subject.name}")
#                 continue

#             teacher = Teacher.query.get(assignment.teacher_id)

#             print(f"   ✅ {subject.name} → {teacher.name}")

#             subjects.append(subject)
#             teachers.append(teacher)

#         if not subjects:
#             print("❌ No valid subjects in this group")
#             continue

#         # -----------------------------
#         # TRY ALL SLOTS
#         # -----------------------------
#         print("\n🔍 SLOT CHECKING...")

#         found_slot = False

#         for day in DAYS:
#             for slot in TIME_SLOTS:

#                 print(f"\nChecking {day} | {slot}")

#                 valid = True

#                 # -----------------------------
#                 # CLASS CONFLICT
#                 # -----------------------------
#                 class_conflict = TimetableEntry.query.filter_by(
#                     class_id=cls.id,
#                     day=day,
#                     slot=slot
#                 ).first()

#                 if class_conflict:
#                     print("❌ Class already occupied")
#                     continue

#                 # -----------------------------
#                 # CHECK EACH TEACHER
#                 # -----------------------------
#                 for t in teachers:

#                     # teacher clash
#                     clash = TimetableEntry.query.filter_by(
#                         teacher_id=t.id,
#                         day=day,
#                         slot=slot
#                     ).first()

#                     if clash:
#                         print(f"❌ Teacher clash: {t.name}")
#                         valid = False
#                         break

#                     # teacher load
#                     load = teacher_daily_load(t.id, day)

#                     if load >= 3:
#                         print(f"❌ Teacher overload: {t.name} ({load})")
#                         valid = False
#                         break

#                 if not valid:
#                     continue

#                 # -----------------------------
#                 # SLOT IS VALID
#                 # -----------------------------
#                 print("✅ VALID SLOT FOUND")
#                 print("Subjects:", [s.name for s in subjects])

#                 found_slot = True
#                 break

#             if found_slot:
#                 break

#         if not found_slot:
#             print("\n❌ NO VALID SLOT FOUND FOR THIS GROUP")

# print("\n===== DEBUG COMPLETE =====")