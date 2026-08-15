"""
SQLAlchemy ORM models implementing the conceptual schema:
agencies -> clients -> users -> shifts / tasks / inspections / leaves / rooms
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, ForeignKey, Boolean
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Agency(Base):
    __tablename__ = "agencies"
    agency_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    contact_email = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    clients = relationship("Client", back_populates="agency")


class Client(Base):
    __tablename__ = "clients"
    client_id = Column(Integer, primary_key=True)
    agency_id = Column(Integer, ForeignKey("agencies.agency_id"))
    name = Column(String, nullable=False)
    city = Column(String)
    room_count = Column(Integer)
    contract_start_date = Column(Date)
    status = Column(String, default="active")

    agency = relationship("Agency", back_populates="clients")
    users = relationship("User", back_populates="client")
    rooms = relationship("Room", back_populates="client")


class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.client_id"))
    agency_id = Column(Integer, ForeignKey("agencies.agency_id"))
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # supervisor | cleaner | checker | head_supervisor | admin
    phone = Column(String)
    hire_date = Column(Date)
    employment_status = Column(String, default="active")  # active | inactive | terminated
    hourly_rate = Column(Float)

    client = relationship("Client", back_populates="users")
    shifts = relationship("Shift", back_populates="user")


class Room(Base):
    __tablename__ = "rooms"
    room_id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.client_id"))
    room_number = Column(String, nullable=False)
    floor = Column(Integer)
    room_type = Column(String)  # standard | suite | deluxe

    client = relationship("Client", back_populates="rooms")


class Shift(Base):
    __tablename__ = "shifts"
    shift_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    client_id = Column(Integer, ForeignKey("clients.client_id"))
    work_date = Column(Date, nullable=False)
    clock_in_time = Column(DateTime)
    clock_out_time = Column(DateTime)
    scheduled_hours = Column(Float)
    actual_hours = Column(Float)
    shift_type = Column(String, default="regular")  # regular | overtime
    status = Column(String, default="present")  # present | absent | late | early_leave

    user = relationship("User", back_populates="shifts")


class Task(Base):
    __tablename__ = "tasks"
    task_id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.client_id"))
    room_id = Column(Integer, ForeignKey("rooms.room_id"))
    assigned_to = Column(Integer, ForeignKey("users.user_id"))
    task_type = Column(String, nullable=False)  # cleaning | checking
    work_date = Column(Date, nullable=False)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    duration_minutes = Column(Float)
    status = Column(String, default="completed")  # pending | in_progress | completed | skipped


class Inspection(Base):
    __tablename__ = "inspections"
    inspection_id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.task_id"))
    checker_id = Column(Integer, ForeignKey("users.user_id"))
    hotel_id = Column(Integer, ForeignKey("hotels.hotel_id"))
    result = Column(String)  # pass | fail | needs_rework
    score = Column(Float)  # 0-100
    inspected_at = Column(DateTime)


class Leave(Base):
    __tablename__ = "leaves"
    leave_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    hotel_id = Column(Integer, ForeignKey("hotels.hotel_id"))
    date_from = Column(Date)
    date_to = Column(Date)
    reason = Column(String)
    status = Column(String, default="approved")
