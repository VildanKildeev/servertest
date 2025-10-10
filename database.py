import os
import databases
import sqlalchemy
from sqlalchemy import Table, Column, Integer, String, Boolean, Date, Float, DateTime, ForeignKey, MetaData, UniqueConstraint
from sqlalchemy.engine import create_engine
from sqlalchemy.sql import func

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Переменная окружения DATABASE_URL не установлена.")

# sslmode=require for Render/Heroku
if "sslmode=" not in DATABASE_URL:
    DATABASE_URL = (DATABASE_URL + ("&" if "?" in DATABASE_URL else "?") + "sslmode=require")

# postgres:// -> postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
database = databases.Database(DATABASE_URL)
metadata = MetaData()

# 1) Справочник городов
cities = Table(
    "cities", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False, unique=True),
)

# 2) Пользователи
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String, nullable=False, unique=True),
    Column("hashed_password", String, nullable=False),
    Column("phone_number", String),
    Column("user_type", String, default="ЗАКАЗЧИК"),  # ЗАКАЗЧИК | ИСПОЛНИТЕЛЬ
    Column("specialization", String),
    Column("is_premium", Boolean, server_default=sqlalchemy.sql.expression.false(), nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("city_id", Integer, ForeignKey("cities.id")),
)

# 3) Заявки на работу
work_requests = Table(
    "work_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("description", String, nullable=False),
    Column("specialization", String, nullable=False),
    Column("budget", Float, nullable=False),
    Column("contact_info", String, nullable=False),
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=False),
    Column("is_premium", Boolean, server_default=sqlalchemy.sql.expression.false(), nullable=False),
    Column("executor_id", Integer, ForeignKey("users.id")),
    Column("status", String, server_default="active", nullable=False),
    Column("is_master_visit_required", Boolean, server_default=sqlalchemy.sql.expression.false(), nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)

# 4) Заявки на спецтехнику
machinery_requests = Table(
    "machinery_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("machinery_type", String, nullable=False),
    Column("description", String),
    Column("rental_date", Date),
    Column("min_rental_hours", Integer, server_default="4", nullable=False),
    Column("rental_price", Float),
    Column("contact_info", String),
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=False),
    Column("is_premium", Boolean, server_default=sqlalchemy.sql.expression.false(), nullable=False),
    Column("executor_id", Integer, ForeignKey("users.id")),
    Column("status", String, server_default="active", nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("has_delivery", Boolean, server_default=sqlalchemy.sql.expression.false(), nullable=False),
    Column("delivery_address", String),
)

# 5) Заявки на инструмент
tool_requests = Table(
    "tool_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("tool_name", String, nullable=False),
    Column("description", String),
    Column("rental_price", Float),
    Column("contact_info", String),
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=False),
    Column("executor_id", Integer, ForeignKey("users.id")),
    Column("status", String, server_default="active", nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("count", Integer, server_default="1", nullable=False),
    Column("rental_start_date", Date),
    Column("rental_end_date", Date),
    Column("has_delivery", Boolean, server_default=sqlalchemy.sql.expression.false(), nullable=False),
    Column("delivery_address", String),
)

# 6) Объявления о материалах
material_ads = Table(
    "material_ads", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("material_type", String, nullable=False),
    Column("description", String),
    Column("price", Float),
    Column("contact_info", String),
    Column("city_id", Integer, ForeignKey("cities.id"), nullable=False),
    Column("is_premium", Boolean, server_default=sqlalchemy.sql.expression.false(), nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)

# 7) Рейтинги
ratings = Table(
    "ratings", metadata,
    Column("id", Integer, primary_key=True),
    Column("customer_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("executor_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("request_id", Integer, nullable=False),
    Column("request_type", String, nullable=False),  # 'WORK' | 'MACHINERY'
    Column("score", Integer, nullable=False),
    Column("comment", String),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    UniqueConstraint('request_id', 'request_type', name='uq_request_rating'),
)
