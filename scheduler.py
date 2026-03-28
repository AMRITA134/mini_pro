from models import db, Class, Subject, TimetableEntry, TeachingAssignment
from utils.normalize import normalize_slot
import random
from input_processor import SUBJECT_REQUIREMENTS, LAB_ROOM_DATA

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
                            is_lab_hour=False,
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

                        # 🔥 IMPORTANT: rotate teachers
                        "teacher_id": teachers[i % len(teachers)].teacher_id
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
                    # SELECT TEACHER
                    # -----------------------
                    selected_teacher = None

                    for t in lab["teacher_ids"]:

                        if any(TimetableEntry.query.filter_by(
                            teacher_id=t, day=day, slot=s).first()
                            for s in slots):
                            continue

                        if teacher_daily_load(t, day) + block > 3:
                            continue

                        selected_teacher = t
                        break

                    if not selected_teacher:
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
                    for s in slots:
                        db.session.add(TimetableEntry(
                            class_id=cls.id,
                            subject_id=lab["subject_id"],
                            teacher_id=selected_teacher,
                            day=day,
                            slot=s,
                            is_lab_hour=True,
                            lab_rooms=",".join(rooms)
                        ))

                        subject_count[lab["subject_id"]] = subject_count.get(lab["subject_id"], 0) + 1

                    blocks_assigned += 1
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
                        is_lab_hour=False,
                        lab_rooms=None
                    ))

                project_tasks = project_tasks[block:]
                remaining -= block
                break

        # ===============================
        # STEP 4: THEORY
        # ===============================
        random.shuffle(tasks)

        for task in tasks:

            for day in DAYS:

                if cls.name.startswith("S8") and day == "SATURDAY":
                    continue

                # 🔥 NEW CONSTRAINTS
                if teacher_daily_load(task["teacher_id"], day) >= 3:
                    continue

                if subject_daily_count(cls.id, task["subject_id"], day) >= 2:
                    continue

                for slot in TIME_SLOTS:

                    if TimetableEntry.query.filter_by(
                        class_id=cls.id, day=day, slot=slot).first():
                        continue

                    if TimetableEntry.query.filter_by(
                        teacher_id=task["teacher_id"], day=day, slot=slot).first():
                        continue

                    # 🔥 ADD HERE (VERY IMPORTANT)
                    prev_count = 0
                    for j in range(TIME_SLOTS.index(slot)-1, -1, -1):
                        prev = TimetableEntry.query.filter_by(
                            class_id=cls.id,
                            day=day,
                            slot=TIME_SLOTS[j]
                        ).first()

                        if prev and prev.subject_id == task["subject_id"]:
                            prev_count += 1
                        else:
                            break

                    if prev_count >= 2:
                        continue

                    # ✅ INSERT AFTER CHECK
                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=task["subject_id"],
                        teacher_id=task["teacher_id"],
                        day=day,
                        slot=slot,
                        is_lab_hour=False,
                        lab_rooms=None
                    ))

                    subject_count[task["subject_id"]] = subject_count.get(task["subject_id"], 0) + 1
                    break
                else:
                    continue
                break
        # ===============================
        # STEP 5: FILL EMPTY (FINAL FIXED - SMART)
        # ===============================
        for day in DAYS:
            for slot in TIME_SLOTS:
        
                if cls.name.startswith("S8") and day == "SATURDAY":
                    continue

                # skip if already filled
                if TimetableEntry.query.filter_by(
                    class_id=cls.id, day=day, slot=slot).first():
                    continue

                candidates = []

                for subject_id, teachers in subject_map.items():
                    if not teachers:   # ✅ ADD THIS
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

                    # try all teachers (important improvement)
                    for t in teachers:

                        teacher_id = t.teacher_id

                        # teacher clash
                        if TimetableEntry.query.filter_by(
                            teacher_id=teacher_id, day=day, slot=slot).first():
                            continue

                        # 🔥 teacher load control
                        if teacher_daily_load(teacher_id, day) >= 3:
                            continue

                        # 🔥 consecutive check
                        prev_count = 0
                        for j in range(TIME_SLOTS.index(slot)-1, -1, -1):
                            prev = TimetableEntry.query.filter_by(
                                class_id=cls.id,
                                day=day,
                                slot=TIME_SLOTS[j]
                            ).first()

                            if prev and prev.subject_id == subject_id:
                                prev_count += 1
                            else:
                                break

                        if prev_count >= 2:
                            continue

                        # -----------------------
                        # 🎯 SCORING SYSTEM
                        # -----------------------
                        score = (
                            current_count * 3 +     # avoid overused subject
                            daily_count * 5 +       # avoid same day repeat
                            prev_count * 10         # avoid consecutive
                        )

                        candidates.append((score, subject_id, teacher_id))

                # -----------------------
                # ✅ SELECT BEST SUBJECT
                # -----------------------
                if candidates:
                    candidates.sort(key=lambda x: x[0])

                    _, subject_id, teacher_id = candidates[0]

                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=subject_id,
                        teacher_id=teacher_id,
                        day=day,
                        slot=slot,
                        is_lab_hour=False,
                        lab_rooms=None
                    ))
                    subject_count[subject_id] = subject_count.get(subject_id, 0) + 1
        # ===============================
        # STEP 6: RELAX TEACHER LOAD
        # ===============================
        for day in DAYS:
            for slot in TIME_SLOTS:

                if TimetableEntry.query.filter_by(
                    class_id=cls.id, day=day, slot=slot).first():
                    continue

                for subject_id, teachers in subject_map.items():
                    if not teachers:   # ✅ ADD THIS
                        continue

                    subject = subject_cache[subject_id]

                    if subject.is_lab or is_project_subject(subject):
                        continue

                    hours = SUBJECT_REQUIREMENTS.get(cls.id, {}).get(subject_id, 0)

                    if subject_count.get(subject_id, 0) >= hours:
                        continue

                    teacher_id = random.choice(teachers).teacher_id

                    # ❗ skip only teacher clash (NOT load)
                    if TimetableEntry.query.filter_by(
                        teacher_id=teacher_id, day=day, slot=slot).first():
                        continue

                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=subject_id,
                        teacher_id=teacher_id,
                        day=day,
                        slot=slot,
                        is_lab_hour=False,
                        lab_rooms=None
                    ))

                    subject_count[subject_id] = subject_count.get(subject_id, 0) + 1
                    break
        # ===============================
        # STEP 7: FORCE FILL (SAFE)
        # ===============================
        for day in DAYS:
            for slot in TIME_SLOTS:

                if TimetableEntry.query.filter_by(
                    class_id=cls.id, day=day, slot=slot).first():
                    continue

                # 🔥 ADD THIS CHECK
                if not subject_map:
                    continue

                subject_items = list(subject_map.items())

                if not subject_items:
                    continue

                subject_id, teachers = random.choice(subject_items)
                if subject_cache[subject_id].is_lab:
                    continue
                if not teachers:
                    continue

                assigned = False

                # try all teachers first
                for t in teachers:
                    if not TimetableEntry.query.filter_by(
                        teacher_id=t.teacher_id, day=day, slot=slot
                    ).first():

                        db.session.add(TimetableEntry(
                            class_id=cls.id,
                            subject_id=subject_id,
                            teacher_id=t.teacher_id,
                            day=day,
                            slot=slot,
                            is_lab_hour=False,
                            lab_rooms=None
                        ))

                        assigned = True
                        subject_count[subject_id] = subject_count.get(subject_id, 0) + 1
                        break

                # 🔥 LAST fallback (force assign anyway)
                if not assigned:
                    db.session.add(TimetableEntry(
                        class_id=cls.id,
                        subject_id=subject_id,
                        teacher_id=teachers[0].teacher_id,
                        day=day,
                        slot=slot,
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