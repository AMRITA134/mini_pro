from app import app
from models import db, Subject, TeachingAssignment, Class

with app.app_context():

    print("\n===== SUBJECT TABLE DEBUG =====\n")

    subjects = Subject.query.all()

    for s in subjects:
        print(f"[{s.id}] '{s.name}' → is_lab={s.is_lab}")

    print("\n===== DUPLICATE / SIMILAR SUBJECTS =====\n")

    subject_names = {}

    for s in subjects:
        key = s.name.strip().lower()
        subject_names.setdefault(key, []).append(s)

    for name, group in subject_names.items():
        if len(group) > 1:
            print(f"\n⚠️ Duplicate Subject Group: '{name}'")
            for g in group:
                print(f"   ID={g.id}, name='{g.name}', is_lab={g.is_lab}")

    print("\n===== CHECK LAB DETECTION LOGIC =====\n")

    for s in subjects:
        detected_by_name = "lab" in s.name.lower()
        if detected_by_name != s.is_lab:
            print(
                f"❌ MISMATCH → '{s.name}' | "
                f"is_lab={s.is_lab} | name_detected={detected_by_name}"
            )

    print("\n===== CLASS-WISE SUBJECT USAGE =====\n")

    classes = Class.query.all()

    for cls in classes:
        print(f"\nClass: {cls.name}")

        assignments = TeachingAssignment.query.filter_by(class_id=cls.id).all()

        if not assignments:
            print("   ⚠️ No assignments")
            continue

        for a in assignments:
            subject = Subject.query.get(a.subject_id)
            print(f"   {subject.name} → is_lab={subject.is_lab}")