import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
import os
import databases
from sqlalchemy.types import JSON
from datetime import datetime

# =======================================================
# 1. КОНФИГУРАЦИЯ БАЗЫ ДАННЫХ
# =======================================================

# Получаем DATABASE_URL из переменных окружения.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Проверяем, что переменная установлена
if not DATABASE_URL:
    # Используем SQLite для локальной разработки, если URL не задан
    DATABASE_URL = "sqlite:///./local_app.db"
    print("ВНИМАНИЕ: DATABASE_URL не задан, используется локальная SQLite база данных.")

# Добавляем параметр SSL для Render.com/Heroku (для PostgreSQL), если его нет.
if "postgres" in DATABASE_URL:
    if "?" in DATABASE_URL:
        if "sslmode" not in DATABASE_URL:
            DATABASE_URL += "&sslmode=require"
    else:
        DATABASE_URL += "?sslmode=require"

# ИСПРАВЛЕНИЕ: Render/Heroku дают URL в формате postgres://,
# но SQLAlchemy требует для asyncpg/databases формат postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Создание объектов SQLAlchemy и Databases
engine = create_engine(DATABASE_URL)
database = databases.Database(DATABASE_URL)
metadata = MetaData()

# =======================================================
# 2. ОПРЕДЕЛЕНИЕ СТРУКТУРЫ ТАБЛИЦ
# =======================================================

# Таблица для пользователей (Users)
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String, unique=True, index=True, nullable=False),
    sqlalchemy.Column("hashed_password", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("first_name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("phone_number", sqlalchemy.String, unique=True, index=True, nullable=False),
    sqlalchemy.Column("user_type", sqlalchemy.String, nullable=False), # "ЗАКАЗЧИК" или "ИСПОЛНИТЕЛЬ"
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("city_id", sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False, nullable=False),
    sqlalchemy.Column("is_active", sqlalchemy.Boolean, default=True),
    sqlalchemy.Column("rating", sqlalchemy.Float, default=0.0),
    sqlalchemy.Column("rating_count", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow)
)

# Таблица для городов (Cities) - Справочник
cities = sqlalchemy.Table(
    "cities",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True, nullable=False),
)

# Таблица для заявок на работу (Work Requests) - Самый главный тип объявлений
work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.ForeignKey("users.id"), nullable=False),
    # НОВОЕ: ID исполнителя, который взял заявку
    sqlalchemy.Column("executor_id", sqlalchemy.ForeignKey("users.id"), nullable=True), 
    sqlalchemy.Column("city_id", sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False), # Добавлено поле name из схемы
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.Text, nullable=False),
    sqlalchemy.Column("budget", sqlalchemy.Float, nullable=True), # Изменен тип на Float
    sqlalchemy.Column("phone_number", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("address", sqlalchemy.String, nullable=True), # Добавлено поле address
    sqlalchemy.Column("visit_date", sqlalchemy.DateTime, nullable=True), # Добавлено поле visit_date
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
    # НОВОЕ: Поле, чтобы отслеживать, взята ли заявка
    sqlalchemy.Column("is_taken", sqlalchemy.Boolean, default=False, nullable=False),
    # Поле status больше не нужно, так как is_taken его заменяет для фильтрации
)

# Таблица для объявлений о спецтехнике (Machinery Ads)
machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.ForeignKey("users.id"), nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("machinery_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.Text, nullable=True),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("rental_price", sqlalchemy.Float, nullable=False), # Цена за час
    # НОВЫЕ ПОЛЯ
    sqlalchemy.Column("rental_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("min_hours_4", sqlalchemy.Boolean, default=True),
    sqlalchemy.Column("hours_count", sqlalchemy.Integer, nullable=True),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow)
)

# Таблица для объявлений об инструментах (Tool Ads)
tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.ForeignKey("users.id"), nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("tool_name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.Text, nullable=True),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("rental_price", sqlalchemy.Float, nullable=False), # Цена в сутки
    # НОВЫЕ ПОЛЯ
    sqlalchemy.Column("rental_start_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("rental_end_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("has_delivery", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("delivery_address", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow)
)


# Таблица для объявлений о материалах (Material Ads)
material_ads = sqlalchemy.Table(
    "material_ads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.ForeignKey("users.id"), nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("material_type_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("material_types.id"), nullable=False),
    sqlalchemy.Column("description", sqlalchemy.Text, nullable=False),
    sqlalchemy.Column("phone_number", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("price", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow)
)


# =======================================================
# 3. ТАБЛИЦЫ-СПРАВОЧНИКИ (LOOKUP TABLES)
# =======================================================

# Инициализационные данные для справочников (Lookup Data)

initial_cities = [
    {"name": "Москва"}, {"name": "Санкт-Петербург"}, {"name": "Екатеринбург"}, {"name": "Казань"}, {"name": "Новосибирск"}
]

initial_specializations = [
    {"name": "Электрик"}, {"name": "Сантехник"}, {"name": "Плиточник"}, {"name": "Маляр"}, {"name": "Сварщик"}, {"name": "Грузчик"}, {"name": "Разнорабочий"}
]

initial_machinery_types = [
    {"name": "Экскаватор"}, {"name": "Бульдозер"}, {"name": "Автокран"}, {"name": "Самосвал"}, {"name": "Манипулятор"}, {"name": "Ямобур"}
]

initial_tool_types = [
    {"name": "Перфоратор"}, {"name": "Бетономешалка"}, {"name": "Виброплита"}, {"name": "Отбойный молоток"}, {"name": "Генератор"}, {"name": "Сварочный аппарат"}
]

initial_material_types = [
    {"name": "Цемент"}, {"name": "Песок"}, {"name": "Кирпич"}, {"name": "Гипсокартон"}, {"name": "Утеплитель"}, {"name": "Пиломатериалы"}
]

# Создаем метаданные для справочников
specializations = sqlalchemy.Table(
    "specializations", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True, nullable=False)
)

machinery_types = sqlalchemy.Table(
    "machinery_types", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True, nullable=False)
)

tool_types = sqlalchemy.Table(
    "tool_types", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True, nullable=False)
)

material_types = sqlalchemy.Table(
    "material_types", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True, nullable=False)
)