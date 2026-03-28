from app import app
from models import db, TimetableEntry, TeachingAssignment, Subject

def reset_database():
    print("⚠️ Resetting database...")

    TimetableEntry.query.delete()
    TeachingAssignment.query.delete()
    Subject.query.delete()

    db.session.commit()

    print("✅ Database reset complete!")

if __name__ == "__main__":
    with app.app_context():
        reset_database()