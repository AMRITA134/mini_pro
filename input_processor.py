import pandas as pd
from models import db, Class, Room, Teacher, Subject, TimetableEntry, User,TeachingAssignment
from utils.normalize import normalize_slot, normalize_subject
SUBJECT_REQUIREMENTS = {}
PARALLEL_DATA = {}
LAB_ROOM_DATA = {}
SUBJECT_TYPE = {}

def load_lab_rooms():

    global LAB_ROOM_DATA

    LAB_ROOM_DATA.clear()

    df = normalize(pd.read_excel("uploads/lab_rooms.xlsx"))

    class_col = get_class_column(df)

    subject_col = "subject" if "subject" in df.columns else "subject_name"

    for _, r in df.iterrows():

        class_name = str(r[class_col]).strip()
        subject_name = normalize_subject(r[subject_col])
        rooms = str(r["rooms"]).strip()

        cls = Class.query.filter_by(name=class_name).first()
        subject = Subject.query.filter_by(name=subject_name).first()

        if subject and subject.is_lab != (SUBJECT_TYPE.get(subject_name) == "lab"):
            print(f"⚠️ FIXING SUBJECT TYPE: {subject_name}")
            subject.is_lab = (SUBJECT_TYPE.get(subject_name) == "lab")

        if not cls or not subject:
            print(f"⚠️ Skipping lab mapping: {class_name} - {subject_name}")
            continue

        LAB_ROOM_DATA[(cls.id, subject.id)] = rooms.split(",")

    print("✅ LAB ROOM DATA LOADED")
    print(LAB_ROOM_DATA)  # 🔥 DEBUG

def normalize(df):
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
    )
    return df


def get_class_column(df):
    for c in ["class", "class_name"]:
        if c in df.columns:
            return c
    raise ValueError(f"No class column found. Columns: {list(df.columns)}")


def get_slot_column(df):
    for c in ["slot", "period", "time", "time_slot"]:
        if c in df.columns:
            return c
    raise ValueError(f"No slot column found. Columns: {list(df.columns)}")

def delete_base_entry(class_id, day, slot):

    base_entries = TimetableEntry.query.filter(
        TimetableEntry.class_id == class_id,
        TimetableEntry.day == day,
        TimetableEntry.slot == slot,
        TimetableEntry.batch.is_(None),
        TimetableEntry.is_lab_hour == False
    ).all()

    for e in base_entries:
        db.session.delete(e)


def process_inputs():

    print("\n========== INPUT PROCESSOR START ==========\n")
    SUBJECT_REQUIREMENTS.clear()
    LAB_ROOM_DATA.clear()
    PARALLEL_DATA.clear()
    TimetableEntry.query.delete()
    TeachingAssignment.query.delete()
    Subject.query.delete()
    TeachingAssignment.query.delete() 
    Subject.query.delete()
    Teacher.query.delete()
    Room.query.delete()
    Class.query.delete()
    db.session.commit()

    df = normalize(pd.read_excel("uploads/class_strength.xlsx"))
    class_col = get_class_column(df)

    class_map = {}

    for _, r in df.iterrows():

        cls = Class(
            name=str(r[class_col]).strip(),
            strength=int(r["strength"]),
            class_category=str(r["class_category"]).lower()
        )

        db.session.add(cls)
        db.session.flush()

        class_map[cls.name] = cls

    df = normalize(pd.read_excel("uploads/room_mapping.xlsx"))
    class_col = get_class_column(df)

    for _, r in df.iterrows():

        class_name = str(r[class_col]).strip()

        cls = class_map.get(class_name)

        room_name = str(r["room"]).strip()
        capacity = int(r["capacity"])

        if cls:

            db.session.add(Room(
                name=room_name,
                capacity=capacity,
                is_permanent=True,
                owner_class_id=cls.id
            ))

        else:

            db.session.add(Room(
                name=room_name,
                capacity=capacity,
                is_permanent=False,
                owner_class_id=None
            ))

    df = normalize(pd.read_excel("uploads/class_type.xlsx"))

    global SUBJECT_TYPE

    SUBJECT_TYPE = {
        normalize_subject(r["subject"]): str(r["type"]).lower()
        for _, r in df.iterrows()
    }

    df = pd.read_excel("uploads/teacher_subject_mapping.xlsx")

    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
    )

    print("Teacher Mapping Columns:", df.columns.tolist())

    required_columns = ["faculty", "subject", "class"]

    for col in required_columns:
        if col not in df.columns:
            raise Exception(f"Column '{col}' missing in teacher_subject_mapping.xlsx")

    teacher_map = {}
    subject_map = {}

    for _, r in df.iterrows():

        faculty = str(r.get("faculty", "")).strip()
        subject_name = normalize_subject(str(r.get("subject", "")).strip())
        class_name = (
            str(r.get("class", ""))
            .strip()
            .replace(" ", "_")
            .replace("-", "_")
        )

        if not faculty or not subject_name or not class_name:
            continue

        cls = class_map.get(class_name)

        if not cls:
            continue
        teacher = teacher_map.get(faculty)

        if not teacher:

            teacher = Teacher(name=faculty)

            db.session.add(teacher)
            db.session.flush()

            teacher_map[faculty] = teacher

            email = faculty.lower().replace(" ", "") + "@college.edu"

            existing_user = User.query.filter_by(email=email).first()

            if not existing_user:

                teacher_user = User(
                    email=email,
                    role="teacher",
                    teacher_id=teacher.id
                )

                teacher_user.set_password("teacher123")

                db.session.add(teacher_user)

        subject = Subject.query.filter_by(name=subject_name).first()

        if subject and subject.is_lab != (SUBJECT_TYPE.get(subject_name) == "lab"):
            print(f"⚠️ FIXING SUBJECT TYPE: {subject_name}")
            subject.is_lab = (SUBJECT_TYPE.get(subject_name) == "lab")

        if not subject:
            subject = Subject(
                name=subject_name,
                is_lab=(SUBJECT_TYPE.get(subject_name) == "lab"),
                teacher_id=teacher.id
            )
            db.session.add(subject)
            db.session.flush()
        else:
            subject.teacher_id = teacher.id

        subject_map[(cls.id, subject_name)] = subject
        existing_assignment = TeachingAssignment.query.filter_by(
            teacher_id=teacher.id,
            subject_id=subject.id,
            class_id=cls.id
        ).first()

        if not existing_assignment:

            assignment = TeachingAssignment(
                teacher_id=teacher.id,
                subject_id=subject.id,
                class_id=cls.id
            )

            db.session.add(assignment)

    db.session.commit()
    print(f"SUBJECT DEBUG → {subject.name}, is_lab={subject.is_lab}, class={cls.name}")

    # SUBJECT REQUIREMENTS
    df = normalize(pd.read_excel("uploads/subject_requirements.xlsx"))

    class_col = get_class_column(df)

    for _, r in df.iterrows():

        class_name = str(r[class_col]).strip()
        subject_name = normalize_subject(r["subject"])
        hours = int(r["periods_per_week"])

        cls = class_map.get(class_name)
        subject = subject_map.get((cls.id, subject_name))

        if not cls or not subject:
            continue

        SUBJECT_REQUIREMENTS.setdefault(cls.id, {})

        SUBJECT_REQUIREMENTS[cls.id][subject.id] = hours

    df = normalize(pd.read_excel("uploads/parallel_classes.xlsx"))

    class_col = get_class_column(df)
    slot_col = get_slot_column(df)

    for _, r in df.iterrows():

        cls = class_map.get(str(r[class_col]).strip())

        if not cls:
            continue

        subject_name = normalize_subject(r["subject"])
        day = str(r["day"]).strip()
        slot = normalize_slot(r[slot_col])
        batch = str(r["batch"]).strip()

        PARALLEL_DATA.setdefault(cls.id, [])

        
        subject = subject_map.get((cls.id, subject_name))
        if subject is None:
            subject = Subject(name=subject_name)
            db.session.add(subject)
            db.session.flush()
            subject_map[(cls.id, subject_name)] = subject
            print(f"DEBUG → {subject.name}, is_lab={subject.is_lab}, class={cls.name}")

        assignment = TeachingAssignment.query.filter_by(
            subject_id=subject.id,
            class_id=cls.id
        ).first()


        teacher_id = assignment.teacher_id if assignment else None
        PARALLEL_DATA[cls.id].append({
        "subject_id": subject.id,
        "day": day,
        "slot": slot,
        "batch": batch
    })

    df = normalize(pd.read_excel("uploads/student_mapping.xlsx"))

    class_col = get_class_column(df)

    for _, r in df.iterrows():

        class_name = str(r[class_col]).strip()

        cls = class_map.get(class_name)

        if not cls:
            continue

        email = str(r["email"]).strip().lower()

        if User.query.filter_by(email=email).first():
            continue

        student_user = User(
            email=email,
            role="student",
            class_id=cls.id
        )

        student_user.set_password("student123")

        db.session.add(student_user)


    db.session.commit()
    load_lab_rooms()

    print("\n========== INPUT PROCESSOR DONE ==========\n")

