"""
Generates realistic synthetic data for the hotel cleaning workforce app:
1 agency -> 3 hotels -> supervisors/cleaners/checkers -> 60 days of
shifts, cleaning/checking tasks, and inspections.

Run: python -m app.seed_data
"""
import random
from datetime import date, datetime, timedelta

from faker import Faker
from sqlalchemy.orm import Session

from app.database import engine, SessionLocal
from app.models import (
    Base, Agency, Hotel, User, Room, Shift, Task, Inspection, Leave
)

fake = Faker()
random.seed(42)
Faker.seed(42)

NUM_DAYS_HISTORY = 60
TODAY = date.today()

HOTELS = [
    {"name": "Grand Meridian Hotel", "city": "Berlin", "room_count": 90},
    {"name": "Harbor View Suites", "city": "Hamburg", "room_count": 70},
    {"name": "Alpine Plaza Hotel", "city": "Munich", "room_count": 60},
]

ROOM_TYPES = ["standard", "standard", "standard", "deluxe", "suite"]


def build_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_org(db: Session):
    agency = Agency(name="CleanSweep Facility Services", contact_email="ops@cleansweep.example")
    db.add(agency)
    db.flush()

    hotels = []
    for h in HOTELS:
        hotel = Hotel(
            agency_id=agency.agency_id,
            name=h["name"],
            city=h["city"],
            room_count=h["room_count"],
            contract_start_date=TODAY - timedelta(days=random.randint(200, 900)),
            status="active",
        )
        db.add(hotel)
        db.flush()
        hotels.append(hotel)

    db.commit()
    return agency, hotels


def seed_users(db: Session, agency, hotels):
    users_by_hotel = {}

    # Head of supervisors - oversees the whole agency, not tied to one hotel
    head = User(
        hotel_id=hotels[0].hotel_id,  # nominal home base
        agency_id=agency.agency_id,
        full_name="Priya Nandakumar",
        role="head_supervisor",
        phone=fake.phone_number(),
        hire_date=TODAY - timedelta(days=800),
        employment_status="active",
        hourly_rate=28.0,
    )
    db.add(head)
    db.flush()

    for hotel in hotels:
        cleaners, checkers = [], []

        supervisor = User(
            hotel_id=hotel.hotel_id, agency_id=agency.agency_id,
            full_name=fake.name(), role="supervisor",
            phone=fake.phone_number(),
            hire_date=TODAY - timedelta(days=random.randint(300, 700)),
            employment_status="active", hourly_rate=22.0,
        )
        db.add(supervisor)
        db.flush()

        for _ in range(20):
            c = User(
                hotel_id=hotel.hotel_id, agency_id=agency.agency_id,
                full_name=fake.name(), role="cleaner",
                phone=fake.phone_number(),
                hire_date=TODAY - timedelta(days=random.randint(10, 600)),
                employment_status=random.choices(
                    ["active", "inactive"], weights=[0.93, 0.07])[0],
                hourly_rate=round(random.uniform(13.5, 16.5), 2),
            )
            db.add(c)
            cleaners.append(c)

        for _ in range(5):
            k = User(
                hotel_id=hotel.hotel_id, agency_id=agency.agency_id,
                full_name=fake.name(), role="checker",
                phone=fake.phone_number(),
                hire_date=TODAY - timedelta(days=random.randint(10, 600)),
                employment_status="active",
                hourly_rate=round(random.uniform(15.5, 18.5), 2),
            )
            db.add(k)
            checkers.append(k)

        db.flush()
        users_by_hotel[hotel.hotel_id] = {
            "supervisor": supervisor, "cleaners": cleaners, "checkers": checkers
        }

    db.commit()
    return head, users_by_hotel


def seed_rooms(db: Session, hotels):
    rooms_by_hotel = {}
    for hotel in hotels:
        rooms = []
        for i in range(hotel.room_count):
            floor = i // 20 + 1
            room = Room(
                hotel_id=hotel.hotel_id,
                room_number=f"{floor}{str(i % 20 + 1).zfill(2)}",
                floor=floor,
                room_type=random.choice(ROOM_TYPES),
            )
            db.add(room)
            rooms.append(room)
        db.flush()
        rooms_by_hotel[hotel.hotel_id] = rooms
    db.commit()
    return rooms_by_hotel


def seed_operations(db: Session, hotels, users_by_hotel, rooms_by_hotel):
    """Generate shifts, cleaning/checking tasks, and inspections for each
    hotel across NUM_DAYS_HISTORY days."""
    shift_id = task_id = inspection_id = leave_id = 0

    for hotel in hotels:
        cleaners = [u for u in users_by_hotel[hotel.hotel_id]["cleaners"] if u.employment_status == "active"]
        checkers = users_by_hotel[hotel.hotel_id]["checkers"]
        rooms = rooms_by_hotel[hotel.hotel_id]

        # a couple of workers are consistently strong performers, one is weak - gives
        # the "top workers" / "underperforming worker" questions a real signal
        star_cleaners = random.sample(cleaners, k=min(3, len(cleaners)))
        weak_cleaner = random.choice([c for c in cleaners if c not in star_cleaners])

        for day_offset in range(NUM_DAYS_HISTORY, -1, -1):
            work_date = TODAY - timedelta(days=day_offset)
            is_weekend = work_date.weekday() >= 5

            for cleaner in cleaners:
                # attendance pattern
                absence_p = 0.10 if cleaner is weak_cleaner else 0.045
                if random.random() < absence_p:
                    db.add(Shift(
                        user_id=cleaner.user_id, hotel_id=hotel.hotel_id,
                        work_date=work_date, scheduled_hours=8.0, actual_hours=0.0,
                        status="absent",
                    ))
                    if random.random() < 0.3:
                        db.add(Leave(
                            user_id=cleaner.user_id, hotel_id=hotel.hotel_id,
                            date_from=work_date, date_to=work_date,
                            reason=random.choice(["sick", "personal", "family emergency"]),
                            status="approved",
                        ))
                    continue

                late = random.random() < (0.18 if cleaner is weak_cleaner else 0.08)
                clock_in_hour = 8 + (1 if late else 0)
                clock_in = datetime.combine(work_date, datetime.min.time()) + timedelta(
                    hours=clock_in_hour, minutes=random.randint(0, 45))
                overtime = random.random() < (0.12 if is_weekend else 0.08)
                base_hours = round(random.uniform(7.0, 8.5), 2)
                actual_hours = round(base_hours + (random.uniform(1, 2.5) if overtime else 0), 2)
                clock_out = clock_in + timedelta(hours=actual_hours)

                db.add(Shift(
                    user_id=cleaner.user_id, hotel_id=hotel.hotel_id,
                    work_date=work_date, clock_in_time=clock_in, clock_out_time=clock_out,
                    scheduled_hours=8.0, actual_hours=actual_hours,
                    shift_type="overtime" if overtime else "regular",
                    status="late" if late else "present",
                ))

                # each active cleaner completes several room cleaning tasks that day
                perf_bonus = cleaner in star_cleaners
                n_tasks = random.randint(7, 11) + (2 if perf_bonus else 0)
                n_tasks = min(n_tasks, len(rooms))
                todays_rooms = random.sample(rooms, k=n_tasks)
                cursor = clock_in + timedelta(minutes=15)

                for room in todays_rooms:
                    duration = random.randint(18, 30) if perf_bonus else random.randint(25, 55)
                    if room.room_type == "suite":
                        duration += random.randint(15, 30)
                    start = cursor
                    end = start + timedelta(minutes=duration)
                    cursor = end + timedelta(minutes=random.randint(3, 10))

                    t = Task(
                        hotel_id=hotel.hotel_id, room_id=room.room_id,
                        assigned_to=cleaner.user_id, task_type="cleaning",
                        work_date=work_date, start_time=start, end_time=end,
                        duration_minutes=duration, status="completed",
                    )
                    db.add(t)
                    db.flush()

                    # ~55% of completed cleanings get inspected same day
                    if checkers and random.random() < 0.55:
                        checker = random.choice(checkers)
                        fail_p = 0.22 if cleaner is weak_cleaner else 0.06
                        result = "fail" if random.random() < fail_p else "pass"
                        score = round(random.uniform(55, 74), 1) if result == "fail" else round(random.uniform(82, 100), 1)
                        db.add(Inspection(
                            task_id=t.task_id, checker_id=checker.user_id,
                            hotel_id=hotel.hotel_id, result=result, score=score,
                            inspected_at=end + timedelta(minutes=random.randint(10, 90)),
                        ))

            # checkers also get their own attendance shift rows
            for checker in checkers:
                if random.random() < 0.05:
                    db.add(Shift(
                        user_id=checker.user_id, hotel_id=hotel.hotel_id,
                        work_date=work_date, scheduled_hours=8.0, actual_hours=0.0,
                        status="absent",
                    ))
                    continue
                clock_in = datetime.combine(work_date, datetime.min.time()) + timedelta(
                    hours=8, minutes=random.randint(0, 30))
                actual_hours = round(random.uniform(7.5, 8.5), 2)
                db.add(Shift(
                    user_id=checker.user_id, hotel_id=hotel.hotel_id,
                    work_date=work_date, clock_in_time=clock_in,
                    clock_out_time=clock_in + timedelta(hours=actual_hours),
                    scheduled_hours=8.0, actual_hours=actual_hours,
                    shift_type="regular", status="present",
                ))

            # supervisor attendance too (lighter touch)
            sup = users_by_hotel[hotel.hotel_id]["supervisor"]
            if random.random() > 0.03 and not is_weekend:
                clock_in = datetime.combine(work_date, datetime.min.time()) + timedelta(hours=7, minutes=45)
                db.add(Shift(
                    user_id=sup.user_id, hotel_id=hotel.hotel_id,
                    work_date=work_date, clock_in_time=clock_in,
                    clock_out_time=clock_in + timedelta(hours=9),
                    scheduled_hours=8.0, actual_hours=9.0,
                    shift_type="regular", status="present",
                ))

        db.commit()
        print(f"Seeded operations for {hotel.name}")


def run():
    build_schema()
    db = SessionLocal()
    try:
        agency, hotels = seed_org(db)
        head, users_by_hotel = seed_users(db, agency, hotels)
        rooms_by_hotel = seed_rooms(db, hotels)
        seed_operations(db, hotels, users_by_hotel, rooms_by_hotel)
        print("Seed complete.")
        print(f"Agency: {agency.name}")
        for h in hotels:
            print(f"  Hotel: {h.name} ({h.city}), {h.room_count} rooms")
        print(f"Head of supervisors: {head.full_name}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
