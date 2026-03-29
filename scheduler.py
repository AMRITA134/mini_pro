from models import db, Class, Subject, TimetableEntry, TeachingAssignment
from utils.normalize import normalize_slot
import random
from input_processor import SUBJECT_REQUIREMENTS, LAB_ROOM_DATA, PARALLEL_DATA, delete_base_entry

DAYS = ["MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY"]

TIME_SLOTS = list(map(normalize_slot, [
    "8.00-8.45","9.10-9.55","10.00-10.45",
    "10.50-11.35","11.55-12.40","12.45-1.30"
]))

# -----------------------------
# HELPERS
# -----------------------------
def is_lab_subject(subject):
    return subject and subject.is_lab
def is_project_subject(subject):
    return subject and "project" in subject.name.lower()

def is_room_conflict(day, slots, rooms):
    for s in slots:
        existing = TimetableEntry.query.filter(
            TimetableEntry.day == day,
            TimetableEntry.slot == s,
            TimetableEntry.is_lab_hour == True
        ).all()

        for e in existing:
            if e.lab_rooms:
                used = [r.strip() for r in e.lab_rooms.split(",")]
                for room in rooms:
                    if room.strip() in used:
                        return True
    return False
# -----------------------------
# LOAD CONSTRAINTS
# -----------------------------
def teacher_daily_load(teacher_id, day):
    return TimetableEntry.query.filter_by(
        teacher_id=teacher_id,
        day=day
    ).count()


def subject_daily_count(class_id, subject_id, day):
    return TimetableEntry.query.filter_by(
        class_id=class_id,
        subject_id=subject_id,
        day=day
    ).count()


# -----------------------------
# MAIN FUNCTION
# -----------------------------
def generate_timetable():
    print("⚡ Generating timetable...")
    subject_cache = {s.id: s for s in Subject.query.all()}

    TimetableEntry.query.delete()
    db.session.commit()

    classes = Class.query.all()

    for cls in classes:

        assignments = TeachingAssignment.query.filter_by(class_id=cls.id).all()
        if not assignments:
            print(f"⏭️ Skipping {cls.name} (no teacher mapping)")
            continue

        subject_map = {}
        for a in assignments:
            subject_map.setdefault(a.subject_id, []).append(a)

        tasks = []
        lab_tasks = []
        project_tasks = []
        subject_count = {}

        # ===============================
        # STEP 0: S8 SATURDAY FULL PROJECT
        # ===============================
        if cls.name.startswith("S8"):

            for subject_id in subject_map:
                subject = subject_cache[subject_id]

                if is_project_subject(subject):

                    teachers = subject_map.get(subject_id, [])
                    if not teachers:
                        continue
                    teacher_id = teachers[0].teacher_id if teachers else None

                    for slot in TIME_SLOTS:
                        db.session.add(TimetableEntry(
                            class_id=cls.id,
                            subject_id=subject_id,
                            teacher_id=teacher_id,
                            day="SATURDAY",
                            slot=slot,
                            is_lab_hour = subject_cache[subject_id].is_lab,
                            lab_rooms=None
                        ))

                    if cls.id in SUBJECT_REQUIREMENTS:
                        SUBJECT_REQUIREMENTS[cls.id][subject_id] = max(
                            0,
                            SUBJECT_REQUIREMENTS[cls.id][subject_id] - len(TIME_SLOTS)
                        )

                    break

        # ===============================
        # STEP 1: SPLIT TASKS (FINAL FIXED)
        # ===============================
        for subject_id, teachers in subject_map.items():
            if not teachers:
                continue  

            subject = subject_cache[subject_id]

            # get required hours
            hours = SUBJECT_REQUIREMENTS.get(
                cls.id, {}
            ).get(subject_id, teachers[0].hours_per_week)

            # -----------------------
            # LAB SUBJECT
            # -----------------------
            if is_lab_subject(subject):

                lab_tasks.append({
                    "subject_id": subject_id,
                    "teacher_ids": [t.teacher_id for t in teachers],
                    "hours": hours
                })

            # -----------------------
            # PROJECT SUBJECT
            # -----------------------
            elif is_project_subject(subject):

                for i in range(hours):
                    project_tasks.append({
                        "subject_id": subject_id,
                        # 🔥 rotate teachers if multiple
                        "teacher_id": teachers[i % len(teachers)].teacher_id
                    })

            # -----------------------
            # THEORY SUBJECT
            # -----------------------
            else:

                for i in range(hours):
                    tasks.append({
                        "subject_id": subject_id,
                        "teacher_id": teachers[i % len(teachers)].teacher_id,
                    })

        # ===============================
        # STEP 2: LABS (FINAL CLEAN FIX)
        # ===============================
        for lab in lab_tasks:

            total_blocks = lab["hours"] // 3
            blocks_assigned = 0

            for day in DAYS:

                if blocks_assigned >= total_blocks:
                    break

                if not cls.name.startswith("S8") and day == "SATURDAY":
                    continue

                block = 3

                for i in range(len(TIME_SLOTS) - (block - 1)):

                    slots = TIME_SLOTS[i:i+block]

                    # -----------------------
                    # CLASS CONFLICT
                    # -----------------------
                    if any(TimetableEntry.query.filter_by(
                        class_id=cls.id, day=day, slot=s).first()
                        for s in slots):
                        continue

                    # -----------------------
                    # SELECT MULTIPLE TEACHERS
                    # -----------------------
                    valid_teachers = []

                    for t in lab["teacher_ids"]:

                        # teacher conflict check
                        if any(TimetableEntry.query.filter_by(
                            teacher_id=t, day=day, slot=s).first()
                            for s in slots):
                            continue

                        # daily load check
                        if teacher_daily_load(t, day) + block > 4:
                            continue

                        valid_teachers.append(t)

                    if not valid_teachers:
                        continue

                    # -----------------------
                    # ROOM CHECK
                    # -----------------------
                    rooms = LAB_ROOM_DATA.get((cls.id, lab["subject_id"]), [])

                    if not rooms:
                        print(f"❌ No lab rooms for class {cls.id}, subject {lab['subject_id']}")
                        continue

                    if is_room_conflict(day, slots, rooms):
                        continue

                    # -----------------------
                    # ASSIGN LAB BLOCK
                    # -----------------------
                    teacher_ids = lab["teacher_ids"]

                    for s in slots:
                        for t_id in teacher_ids:

                            # avoid teacher conflict
                            if TimetableEntry.query.filter_by(
                                teacher_id=t_id,
                                day=day,
                                slot=s
                            ).first():
                                continue

                            db.session.add(TimetableEntry(
                                class_id=cls.id,
                                subject_id=lab["subject_id"],
                                teacher_id=t_id,
                                day=day,
                                slot=s,
                                is_lab_hour=True,
                                lab_rooms=",".join(rooms)
                            ))

                        # count per slot, not per teacher
                        if s == slots[0]:
                            subject_count[lab["subject_id"]] = subject_count.get(lab["subject_id"], 0) + block
                    blocks_assigned += 1
                    if cls.id in SUBJECT_REQUIREMENTS and lab["subject_id"] in SUBJECT_REQUIREMENTS[cls.id]:
                        SUBJECT_REQUIREMENTS[cls.id][lab["subject_id"]] -= block
                    break   # ✅ move to next day
        # ===============================
        # STEP 3: PROJECT BLOCKS (FINAL)
        # ===============================
        remaining = len(project_tasks)

        for day in DAYS:

            if remaining <= 0:
                break

            # skip Saturday for S8 (already filled)
            if cls.name.startswith("S8") and day == "SATURDAY":
                continue

            subject_id = project_tasks[0]["subject_id"]
            teacher = project_tasks[0]["teacher_id"]

            # 🔥 LIMITS
            # max 2 project periods per day
            if subject_daily_count(cls.id, subject_id, day) >= 2:
                continue

            # max 3 periods per teacher per day
            if teacher_daily_load(teacher, day) >= 3:
                continue

            # block size
            block = 3 if remaining >= 3 else remaining

            # 🔥 adjust block if daily subject limit
            allowed_today = 2 - subject_daily_count(cls.id, subject_id, day)
            block = min(block, allowed_today)

            if block <= 0:
                continue

            for i in range(len(TIME_SLOTS) - (block - 1)):

                slots = TIME_SLOTS[i:i+block]

                # class conflict
                if any(TimetableEntry.query.filter_by(
                    class_id=cls.id, day=day, slot=s).first()
                    for s in slots):
                    continue

                # teacher conflict
                if any(TimetableEntry.query.filter_by(
                    teacher_id=teacher, day=day, slot=s).first()
                    for s in slots):
                    continue

                # 🔥 consecutive limit (avoid >3 same)
                consecutive = 0
                for j in range(i-1, -1, -1):
                    prev = TimetableEntry.query.filter_by(
                        class_id=cls.id,
                        day=day,
                        slot=TIME_SLOTS[j]
                    ).first()

                    if prev and prev.subject_id == subject_id:
                        consecutive += 1
                    else:
                        break

                if consecutive >= 2:
                    continue

                # assign block
                for s in slots:
                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=subject_id,
                        teacher_id=teacher,
                        day=day,
                        slot=s,
                        is_lab_hour=True,
                        lab_rooms=None
                    ))

                project_tasks = project_tasks[block:]
                remaining -= block
                break

        # ===============================
        # STEP X: AUTO PARALLEL (FIXED)
        # ===============================

        parallel_list = PARALLEL_DATA.get(cls.id, [])

        # group by group_id
        parallel_groups = {}

        for p in parallel_list:
            group_id = p.get("group", 1)
            parallel_groups.setdefault(group_id, []).append(p)


        for group_id, group in parallel_groups.items():

            subjects = []
            teachers = []

            # -----------------------
            # BUILD SUBJECT + TEACHER LIST
            # -----------------------
            for p in group:
                subject_id = p["subject_id"]

                # 🔥 SKIP if no remaining hours
                if SUBJECT_REQUIREMENTS.get(cls.id, {}).get(subject_id, 0) <= 0:
                    continue

                assignment = TeachingAssignment.query.filter_by(
                    subject_id=subject_id,
                    class_id=cls.id
                ).first()

                if not assignment:
                    continue

                subjects.append(subject_id)
                teachers.append(assignment.teacher_id)

            # ❌ skip empty groups
            if not subjects:
                continue

            # -----------------------
            # FIND COMMON SLOT
            # -----------------------
            assigned = False

            for day in DAYS:
                for slot in TIME_SLOTS:

                    # skip if class already has something
                    if TimetableEntry.query.filter_by(
                        class_id=cls.id,
                        day=day,
                        slot=slot
                    ).first():
                        continue

                    valid = True

                    # -----------------------
                    # CHECK TEACHER CONSTRAINTS
                    # -----------------------
                    for t in teachers:

                        # teacher clash
                        if TimetableEntry.query.filter_by(
                            teacher_id=t,
                            day=day,
                            slot=slot
                        ).first():
                            valid = False
                            break

                        # 🔥 STRICT DAILY LIMIT (parallel safe)
                        if teacher_daily_load(t, day) >= 3:
                            valid = False
                            break

                    if not valid:
                        continue

                    # -----------------------
                    # ASSIGN ALL PARALLEL SUBJECTS
                    # -----------------------
                    for i, subject_id in enumerate(subjects):

                        db.session.add(TimetableEntry(
                            class_id=cls.id,
                            subject_id=subject_id,
                            teacher_id=teachers[i],
                            day=day,
                            slot=slot,
                            batch=chr(65 + i),   # A, B, C...
                            is_lab_hour = subject_cache[subject_id].is_lab,
                            lab_rooms=None
                        ))

                        # 🔥 UPDATE COUNTS (CRITICAL FIX)
                        subject_count[subject_id] = subject_count.get(subject_id, 0) + 1

                        if cls.id in SUBJECT_REQUIREMENTS and subject_id in SUBJECT_REQUIREMENTS[cls.id]:
                            SUBJECT_REQUIREMENTS[cls.id][subject_id] -= 1

                    assigned = True
                    break

                if assigned:
                    break

        # ===============================
        # STEP 4: THEORY (FINAL FIXED)
        # ===============================

        random.shuffle(tasks)

        # 🔥 PRE-COMPUTE PARALLEL SUBJECTS (IMPORTANT)
        parallel_subject_ids = {
            p["subject_id"]
            for p in PARALLEL_DATA.get(cls.id, [])
        }

        for task in tasks:

            subject_id = task["subject_id"]
            teacher_id = task["teacher_id"]

            # 🚫 SKIP PARALLEL SUBJECTS COMPLETELY
            if subject_id in parallel_subject_ids:
                continue

            for day in DAYS:

                if cls.name.startswith("S8") and day == "SATURDAY":
                    continue

                # 🔥 teacher daily limit
                if teacher_daily_load(teacher_id, day) >= 3:
                    continue

                # 🔥 subject per day limit
                if subject_daily_count(cls.id, subject_id, day) >= 2:
                    continue

                for slot in TIME_SLOTS:

                    # -----------------------
                    # 🚨 SKIP PARALLEL SLOTS
                    # -----------------------
                    if TimetableEntry.query.filter(
                        TimetableEntry.class_id == cls.id,
                        TimetableEntry.day == day,
                        TimetableEntry.slot == slot,
                        TimetableEntry.batch.isnot(None)   # parallel entries
                    ).first():
                        continue

                    # -----------------------
                    # CLASS CONFLICT (ONLY NORMAL)
                    # -----------------------
                    if TimetableEntry.query.filter_by(
                        class_id=cls.id,
                        day=day,
                        slot=slot,
                        batch=None
                    ).first():
                        continue

                    # -----------------------
                    # TEACHER CONFLICT
                    # -----------------------
                    if TimetableEntry.query.filter_by(
                        teacher_id=teacher_id,
                        day=day,
                        slot=slot
                    ).first():
                        continue

                    # -----------------------
                    # CONSECUTIVE SUBJECT CHECK
                    # -----------------------
                    prev_count = 0

                    for j in range(TIME_SLOTS.index(slot) - 1, -1, -1):
                        prev = TimetableEntry.query.filter_by(
                            class_id=cls.id,
                            day=day,
                            slot=TIME_SLOTS[j],
                            batch=None
                        ).first()

                        if prev and prev.subject_id == subject_id:
                            prev_count += 1
                        else:
                            break

                    if prev_count >= 2:
                        continue

                    # -----------------------
                    # INSERT THEORY
                    # -----------------------
                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=subject_id,
                        teacher_id=teacher_id,
                        day=day,
                        slot=slot,
                        batch=None,   # 🔥 ensures NOT parallel
                        is_lab_hour = subject_cache[task["subject_id"]].is_lab,
                        lab_rooms=None
                    ))

                    subject_count[subject_id] = subject_count.get(subject_id, 0) + 1

                    break  # slot loop

                else:
                    continue  # next day

                break  # assigned → move next subject
        # ===============================
        # STEP 5: FILL EMPTY (FINAL FIXED - SAFE)
        # ===============================
        for day in DAYS:
            for slot in TIME_SLOTS:

                if cls.name.startswith("S8") and day == "SATURDAY":
                    continue

                # -----------------------
                # 🚨 BLOCK PARALLEL SLOTS
                # -----------------------
                if TimetableEntry.query.filter(
                    TimetableEntry.class_id == cls.id,
                    TimetableEntry.day == day,
                    TimetableEntry.slot == slot,
                    TimetableEntry.batch.isnot(None)
                ).first():
                    continue

                # -----------------------
                # skip if already filled (normal)
                # -----------------------
                if TimetableEntry.query.filter_by(
                    class_id=cls.id,
                    day=day,
                    slot=slot,
                    batch=None
                ).first():
                    continue

                candidates = []

                for subject_id, teachers in subject_map.items():
                    if not teachers:
                        continue

                    subject = subject_cache[subject_id]

                    # skip lab + project
                    if subject.is_lab or is_project_subject(subject):
                        continue

                    hours = SUBJECT_REQUIREMENTS.get(cls.id, {}).get(subject_id, 0)

                    if hours < 2:
                        continue

                    current_count = subject_count.get(subject_id, 0)

                    if current_count >= hours:
                        continue

                    daily_count = subject_daily_count(cls.id, subject_id, day)

                    if daily_count >= 2:
                        continue

                    for t in teachers:

                        teacher_id = t.teacher_id

                        # teacher clash
                        if TimetableEntry.query.filter_by(
                            teacher_id=teacher_id, day=day, slot=slot).first():
                            continue

                        # teacher load
                        if teacher_daily_load(teacher_id, day) >= 3:
                            continue

                        # consecutive check
                        prev_count = 0
                        for j in range(TIME_SLOTS.index(slot)-1, -1, -1):
                            prev = TimetableEntry.query.filter_by(
                                class_id=cls.id,
                                day=day,
                                slot=TIME_SLOTS[j],
                                batch=None
                            ).first()

                            if prev and prev.subject_id == subject_id:
                                prev_count += 1
                            else:
                                break

                        if prev_count >= 2:
                            continue

                        score = (
                            current_count * 3 +
                            daily_count * 5 +
                            prev_count * 10
                        )

                        candidates.append((score, subject_id, teacher_id))

                if candidates:
                    candidates.sort(key=lambda x: x[0])

                    _, subject_id, teacher_id = candidates[0]

                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=subject_id,
                        teacher_id=teacher_id,
                        day=day,
                        slot=slot,
                        batch=None,
                        is_lab_hour=False,
                        lab_rooms=None
                    ))

                    subject_count[subject_id] = subject_count.get(subject_id, 0) + 1
        # ===============================
        # STEP 6: RELAX TEACHER LOAD (FINAL FIXED)
        # ===============================
        for day in DAYS:
            for slot in TIME_SLOTS:

                # -----------------------
                # 🚨 BLOCK PARALLEL SLOTS
                # -----------------------
                if TimetableEntry.query.filter(
                    TimetableEntry.class_id == cls.id,
                    TimetableEntry.day == day,
                    TimetableEntry.slot == slot,
                    TimetableEntry.batch.isnot(None)
                ).first():
                    continue

                # -----------------------
                # skip if already filled (normal)
                # -----------------------
                if TimetableEntry.query.filter_by(
                    class_id=cls.id,
                    day=day,
                    slot=slot,
                    batch=None
                ).first():
                    continue

                for subject_id, teachers in subject_map.items():
                    if not teachers:
                        continue

                    subject = subject_cache[subject_id]

                    # skip lab + project
                    if subject.is_lab or is_project_subject(subject):
                        continue

                    hours = SUBJECT_REQUIREMENTS.get(cls.id, {}).get(subject_id, 0)

                    if subject_count.get(subject_id, 0) >= hours:
                        continue

                    teacher_id = random.choice(teachers).teacher_id

                    # teacher clash only (relaxed)
                    if TimetableEntry.query.filter_by(
                        teacher_id=teacher_id,
                        day=day,
                        slot=slot
                    ).first():
                        continue

                    # -----------------------
                    # INSERT
                    # -----------------------
                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=subject_id,
                        teacher_id=teacher_id,
                        day=day,
                        slot=slot,
                        batch=None,   # 🔥 IMPORTANT
                        is_lab_hour=False,
                        lab_rooms=None
                    ))

                    subject_count[subject_id] = subject_count.get(subject_id, 0) + 1
                    break
        # ===============================
        # STEP 7: FORCE FILL (FINAL FIXED)
        # ===============================
        for day in DAYS:
            for slot in TIME_SLOTS:

                # -----------------------
                # 🚨 BLOCK PARALLEL SLOTS
                # -----------------------
                if TimetableEntry.query.filter(
                    TimetableEntry.class_id == cls.id,
                    TimetableEntry.day == day,
                    TimetableEntry.slot == slot,
                    TimetableEntry.batch.isnot(None)
                ).first():
                    continue

                # -----------------------
                # skip if already filled (normal)
                # -----------------------
                if TimetableEntry.query.filter_by(
                    class_id=cls.id,
                    day=day,
                    slot=slot,
                    batch=None
                ).first():
                    continue

                # -----------------------
                # SAFETY CHECKS
                # -----------------------
                if not subject_map:
                    continue

                subject_items = list(subject_map.items())

                if not subject_items:
                    continue

                subject_id, teachers = random.choice(subject_items)

                # skip labs
                if subject_cache[subject_id].is_lab:
                    continue

                if not teachers:
                    continue

                assigned = False

                # -----------------------
                # TRY ALL TEACHERS FIRST
                # -----------------------
                for t in teachers:

                    if not TimetableEntry.query.filter_by(
                        teacher_id=t.teacher_id,
                        day=day,
                        slot=slot
                    ).first():

                        db.session.add(TimetableEntry(
                            class_id=cls.id,
                            subject_id=subject_id,
                            teacher_id=t.teacher_id,
                            day=day,
                            slot=slot,
                            batch=None,   # 🔥 IMPORTANT
                            is_lab_hour=False,
                            lab_rooms=None
                        ))

                        subject_count[subject_id] = subject_count.get(subject_id, 0) + 1
                        assigned = True
                        break

                # -----------------------
                # LAST FALLBACK (FORCE)
                # -----------------------
                if not assigned:

                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=subject_id,
                        teacher_id=teachers[0].teacher_id,
                        day=day,
                        slot=slot,
                        batch=None,   # 🔥 IMPORTANT
                        is_lab_hour=False,
                        lab_rooms=None
                    ))

                    subject_count[subject_id] = subject_count.get(subject_id, 0) + 1
    db.session.commit()
    print("✅ Timetable generated!")

from models import Room, Class
import random

def allocate_theory_rooms():
    print("🏫 Allocating theory rooms...")

    entries = TimetableEntry.query.filter(
        TimetableEntry.is_lab_hour == False,
        TimetableEntry.lab_rooms == None
    ).all()

    for e in entries:

        if e.room_id:
            continue

        class_obj = Class.query.get(e.class_id)

        # -----------------------
        # 1. TRY PERMANENT ROOM
        # -----------------------
        permanent_room = Room.query.filter_by(
            owner_class_id=e.class_id,
            is_permanent=True
        ).first()

        if permanent_room:
            conflict = TimetableEntry.query.filter_by(
                room_id=permanent_room.id,
                day=e.day,
                slot=e.slot
            ).first()

            if not conflict:
                e.room_id = permanent_room.id
                continue

        # -----------------------
        # 2. FIND AVAILABLE ROOM
        # -----------------------
        rooms = Room.query.filter(
            Room.capacity >= class_obj.strength
        ).all()

        random.shuffle(rooms)

        for r in rooms:
            conflict = TimetableEntry.query.filter_by(
                room_id=r.id,
                day=e.day,
                slot=e.slot
            ).first()

            if not conflict:
                e.room_id = r.id
                break

    db.session.commit()
    print("✅ Room allocation done!")