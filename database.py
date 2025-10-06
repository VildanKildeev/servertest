import os
from typing import Optional

import sqlalchemy
from sqlalchemy import (
    Table, Column, Integer, String, DateTime, ForeignKey, Text, Float,
    MetaData, create_engine
)
from sqlalchemy.sql import func
import databases

# -----------------------------------------------------------------------------
# DATABASE URL
# -----------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "Переменная окружения DATABASE_URL не установлена. "
        "Укажите строку подключения к БД."
    )

# Добавим sslmode=require для Postgres при отсутствии (актуально для Render и др.)
if DATABASE_URL.startswith("postgres") and "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

database = databases.Database(DATABASE_URL)
metadata = MetaData()
engine = create_engine(DATABASE_URL)

# -----------------------------------------------------------------------------
# Таблицы
# -----------------------------------------------------------------------------
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(255), unique=True, nullable=False, index=True),
    Column("hashed_password", String(255), nullable=False),
    Column("full_name", String(255)),
    Column("role", String(50), default="customer"),
    Column("city_id", Integer),
    Column("created_at", DateTime, server_default=func.now(), nullable=False)
)

cities = Table(
    "cities", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False, unique=True)
)

subscriptions = Table(
    "subscriptions", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("city_id", Integer, ForeignKey("cities.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False)
)

work_requests = Table(
    "work_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("city_id", Integer, ForeignKey("cities.id", ondelete="SET NULL")),
    Column("title", String(255), nullable=False),
    Column("description", Text, nullable=False),
    Column("budget", Float),
    Column("status", String(50), default="open"),
    Column("created_at", DateTime, server_default=func.now(), nullable=False)
)

work_request_offers = Table(
    "work_request_offers", metadata,
    Column("id", Integer, primary_key=True),
    Column("request_id", Integer, ForeignKey("work_requests.id", ondelete="CASCADE"), nullable=False),
    Column("performer_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("price", Float),
    Column("comment", Text),
    Column("status", String(50), default="pending"),  # pending/accepted/rejected
    Column("timestamp", DateTime, server_default=func.now(), nullable=False)
)

machinery_requests = Table(
    "machinery_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("city_id", Integer, ForeignKey("cities.id", ondelete="SET NULL")),
    Column("type", String(120), nullable=False),
    Column("title", String(255), nullable=False),
    Column("description", Text, nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False)
)

tool_requests = Table(
    "tool_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("city_id", Integer, ForeignKey("cities.id", ondelete="SET NULL")),
    Column("tool", String(120), nullable=False),
    Column("title", String(255), nullable=False),
    Column("description", Text, nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False)
)

material_ads = Table(
    "material_ads", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("city_id", Integer, ForeignKey("cities.id", ondelete="SET NULL")),
    Column("material_type", String(120), nullable=False),
    Column("title", String(255), nullable=False),
    Column("description", Text, nullable=False),
    Column("price", Float),
    Column("created_at", DateTime, server_default=func.now(), nullable=False)
)

chat_messages = Table(
    "chat_messages", metadata,
    Column("id", Integer, primary_key=True),
    Column("request_id", Integer, ForeignKey("work_requests.id", ondelete="CASCADE"), nullable=False),
    Column("sender_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("receiver_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("message", Text, nullable=False),
    Column("timestamp", DateTime, server_default=func.now(), nullable=False)
)

machinery_types = Table(
    "machinery_types", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120), unique=True, nullable=False)
)

tools_list = Table(
    "tools_list", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120), unique=True, nullable=False)
)

material_types = Table(
    "material_types", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(120), unique=True, nullable=False)
)
