from app import app
from models import TimetableEntry, Subject

def check_csa_entries():
    print("\n🔍 Checking CSA Timetable Entries:\n")

    entries = TimetableEntry.query.join(Subject).filter(Subject.name == "CSA").all()

    for e in entries:
        print(f"{e.day} | {e.slot} -> is_lab_hour = {e.is_lab_hour}")

if __name__ == "__main__":
     with app.app_context():
         check_csa_entries()