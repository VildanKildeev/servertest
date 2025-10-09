import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
import os
import databases
from sqlalchemy.types import JSON
from sqlalchemy.sql import func # Добавлено для явного использования func.now()

# Получаем DATABASE_URL из переменных окружения.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Проверяем, что переменная установлена
if not DATABASE_URL:
    raise Exception("Переменная окружения DATABASE_URL не установлена. Пожалуйста, установите ее в настройках вашего веб-сервиса на Render.com.")

# --- АДАПТАЦИЯ URL ДЛЯ RENDER/ASYNC ---
# Добавляем параметр SSL для Render.com
if "?" in DATABASE_URL:
    DATABASE_URL += "&sslmode=require"
else:
    DATABASE_URL += "?sslmode=require"

# ИСПРАВЛЕНИЕ: Render/Heroku дают URL в формате postgres://,
# но SQLAlchemy/asyncpg требует формат postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Создание объектов базы данных
engine = create_engine(DATABASE_URL)
database = databases.Database(DATABASE_URL)
metadata = MetaData()
# --- КОНЕЦ НАСТРОЕК БАЗЫ ДАННЫХ ---

# =======================================================================
# 1. Таблица городов (Cities)
# =======================================================================
cities = sqlalchemy.Table(
    "cities",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False, unique=True),
    extend_existing=True,
)

# =======================================================================
# 2. Таблица пользователей (Users)
# =======================================================================
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String, nullable=False, unique=True),
    sqlalchemy.Column("hashed_password", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("phone_number", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("user_type", sqlalchemy.String, default="ЗАКАЗЧИК"), # ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True), # Используется для ИСПОЛНИТЕЛЯ
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id"), nullable=True), 
    
    extend_existing=True,
)

# =======================================================================
# 3. Таблица заявок на работу (Work Requests)
# =======================================================================
work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("budget", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    # СТОЛБЦЫ ДЛЯ ИСПОЛНИТЕЛЯ И СТАТУСА (Work)
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True), 
    sqlalchemy.Column("status", sqlalchemy.String, default="active"), 
    sqlalchemy.Column("is_master_visit_required", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    extend_existing=True,
)

# =======================================================================
# 4. Таблица заявок на спецтехнику (Machinery Requests)
# =======================================================================
machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("machinery_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("min_rental_hours", sqlalchemy.Integer, default=4),
    sqlalchemy.Column("rental_price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    # СТОЛБЦЫ ДЛЯ ИСПОЛНИТЕЛЯ И СТАТУСА (Machinery)
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True), # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 1
    sqlalchemy.Column("status", sqlalchemy.String, default="active"), # КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ 2
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    # Поля для доставки
    sqlalchemy.Column("has_delivery", sqlalchemy.Boolean, default=False, nullable=False),
    sqlalchemy.Column("delivery_address", sqlalchemy.String, nullable=True),
    extend_existing=True,
)

# =======================================================================
# 5. Таблица заявок на инструмент (Tool Requests)
# =======================================================================
tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("tool_name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    # СТОЛБЦЫ ДЛЯ ИСПОЛНИТЕЛЯ И СТАТУСА (Tool)
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True), 
    sqlalchemy.Column("status", sqlalchemy.String, default="active"), 
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    # ОБНОВЛЕННЫЕ СТОЛБЦЫ:
    sqlalchemy.Column("count", sqlalchemy.Integer, default=1),
    sqlalchemy.Column("rental_start_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("rental_end_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("has_delivery", sqlalchemy.Boolean, default=False, nullable=False),
    sqlalchemy.Column("delivery_address", sqlalchemy.String, nullable=True),
    extend_existing=True,
)

# =======================================================================
# 6. Таблица объявлений о материалах (Material Ads)
# =======================================================================
material_ads = sqlalchemy.Table(
    "material_ads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("material_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    extend_existing=True,
)