
import os
from datetime import datetime
import sqlalchemy
from sqlalchemy import Table, Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, MetaData, create_engine, UniqueConstraint
import databases

# ----------------------------------------------------------------------------
# Database configuration
# ----------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL") or "sqlite:///./app.db"

# Async database for FastAPI
database = databases.Database(DATABASE_URL)

# SQLAlchemy metadata/engine
metadata = MetaData()
engine = create_engine(DATABASE_URL)

# ----------------------------------------------------------------------------
# Reference tables
# ----------------------------------------------------------------------------

cities = Table(
    "cities", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, unique=True, nullable=False)
)

specializations = Table(
    "specializations", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, unique=True, nullable=False)
)

machinery_types = Table(
    "machinery_types", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, unique=True, nullable=False)
)

tool_types = Table(
    "tool_types", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, unique=True, nullable=False)
)

material_types = Table(
    "material_types", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, unique=True, nullable=False)
)

# ----------------------------------------------------------------------------
# Core tables
# ----------------------------------------------------------------------------

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String, unique=True, nullable=False),
    Column("hashed_password", String, nullable=False),
    Column("first_name", String, nullable=False),
    Column("user_type", String, nullable=False),  # 'ЗАКАЗЧИК' | 'ИСПОЛНИТЕЛЬ' | 'ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ'
    Column("phone_number", String, nullable=True),
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=True),
    Column("specialization", String, nullable=True),
    Column("rating", Float, nullable=False, server_default="0"),
    Column("rating_count", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

work_requests = Table(
    "work_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("executor_id", Integer, ForeignKey("users.id"), nullable=True),  # кто взял в работу
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=False),
    Column("name", String, nullable=False),
    Column("specialization", String, nullable=False),
    Column("description", Text, nullable=False),
    Column("budget", Float, nullable=True),
    Column("phone_number", String, nullable=False),
    Column("address", String, nullable=True),
    Column("visit_date", DateTime, nullable=True),
    Column("status", String, nullable=False, server_default="open"),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

work_request_ratings = Table(
    "work_request_ratings", metadata,
    Column("id", Integer, primary_key=True),
    Column("work_request_id", Integer, ForeignKey("work_requests.id"), nullable=False),
    Column("rater_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("executor_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("rating_value", Integer, nullable=False),
    UniqueConstraint("work_request_id", "rater_id", name="uq_single_rating_per_request")
)

machinery_requests = Table(
    "machinery_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=False),
    Column("machinery_type", String, nullable=False),
    Column("description", Text, nullable=True),
    Column("rental_price", Float, nullable=True),
    Column("contact_info", String, nullable=False),
    Column("delivery_date", DateTime, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

tool_requests = Table(
    "tool_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=False),
    Column("tool_name", String, nullable=False),
    Column("description", Text, nullable=True),
    Column("rental_price", Float, nullable=True),
    Column("contact_info", String, nullable=False),
    Column("has_delivery", Boolean, nullable=False, server_default="0"),
    Column("delivery_address", String, nullable=True),
    Column("rental_start_date", DateTime, nullable=True),
    Column("rental_end_date", DateTime, nullable=True),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

material_ads = Table(
    "material_ads", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=False),
    Column("material_type", String, nullable=False),   # строковое имя типа (под фронт)
    Column("description", Text, nullable=True),
    Column("price", Float, nullable=False),
    Column("contact_info", String, nullable=False),
    Column("is_premium", Boolean, nullable=False, server_default="0"),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

# ----------------------------------------------------------------------------
# Initial reference data (small safe defaults)
# ----------------------------------------------------------------------------

INITIAL_CITIES = ["Казань", "Москва", "Санкт-Петербург", "Нижний Новгород"]
INITIAL_SPECIALIZATIONS = ["Сантехник", "Электрик", "Строитель", "Отделочник", "Грузчик"]
INITIAL_MACHINERY_TYPES = ["Экскаватор", "Погрузчик", "Кран", "Бульдозер"]
INITIAL_TOOL_TYPES = ["Перфоратор", "Дрель", "Бетономешалка", "Лестница"]
INITIAL_MATERIAL_TYPES = ["Песок", "Щебень", "Цемент", "Кирпич"]

def create_all():
    metadata.create_all(engine)
