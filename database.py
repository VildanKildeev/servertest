import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
import os
import databases
from sqlalchemy.types import JSON
from datetime import datetime

# Получаем DATABASE_URL из переменных окружения.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Проверяем, что переменная установлена
if not DATABASE_URL:
    raise Exception("Переменная окружения DATABASE_URL не установлена. Пожалуйста, установите ее.")

# --- ИСПРАВЛЕНИЯ ДЛЯ RENDER/HEROKU ---
# Добавляем параметр SSL для Render.com, если его нет.
if "?" in DATABASE_URL:
    if "sslmode" not in DATABASE_URL:
        DATABASE_URL += "&sslmode=require"
else:
    DATABASE_URL += "?sslmode=require"

# Render/Heroku дают URL в формате postgres://, но SQLAlchemy/asyncpg требует postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
# --- КОНЕЦ ИСПРАВЛЕНИЙ ---

# Создаем синхронный движок и асинхронное подключение
engine = create_engine(DATABASE_URL)
database = databases.Database(DATABASE_URL)
metadata = MetaData()

# Таблица для городов
cities = sqlalchemy.Table(
    "cities",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True, nullable=False),
    sqlalchemy.Column("region", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("lat", sqlalchemy.Float, nullable=True),
    sqlalchemy.Column("lon", sqlalchemy.Float, nullable=True),
)

# Таблица для пользователей
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String, unique=True, nullable=False),
    sqlalchemy.Column("username", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("hashed_password", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("phone_number", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("user_type", sqlalchemy.String, nullable=False), # worker, customer
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id"), nullable=True),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    # Поля для рейтинга исполнителей
    sqlalchemy.Column("rating", sqlalchemy.Float, default=0.0),
    sqlalchemy.Column("rating_count", sqlalchemy.Integer, default=0),
)

# Таблица для заявок на работу (исполнителя)
work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")), # Заказчик
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True), # Исполнитель
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False), # Имя заказчика
    sqlalchemy.Column("phone_number", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("budget", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("is_taken", sqlalchemy.Boolean, default=False), # Взята ли в работу
    sqlalchemy.Column("chat_enabled", sqlalchemy.Boolean, default=False), # Активирован ли чат
    sqlalchemy.Column("is_completed", sqlalchemy.Boolean, default=False), # Завершена ли заявка
    sqlalchemy.Column("address", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("visit_date", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
)

# Таблица для заявок на спецтехнику
machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("machinery_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_date", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("min_hours", sqlalchemy.Integer, default=4),
    sqlalchemy.Column("rental_price", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
)

# Таблица для заявок на инструмент
tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("tool_name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("tool_count", sqlalchemy.Integer, default=1),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("rental_start", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("rental_end", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("has_delivery", sqlalchemy.Boolean, default=False, nullable=False),
    sqlalchemy.Column("delivery_address", sqlalchemy.String, nullable=True),
)

# Таблица объявлений о материалах
material_ads = sqlalchemy.Table(
    "material_ads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("material_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("price", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False)
)

# Таблица для чата по заявкам на работу (чат привязан только к work_requests)
chat_messages = sqlalchemy.Table(
    "chat_messages",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("request_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("work_requests.id"), nullable=False),
    sqlalchemy.Column("sender_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
    sqlalchemy.Column("message", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Вспомогательные списки для фронтенда (хранение в JSON/константах в идеале, но для простоты здесь)
SPECIALIZATIONS = [
    "Электрик", "Сантехник", "Маляр", "Плотник", "Сварщик", "Разнорабочий",
    "Отделочник", "Кровельщик", "Установщик дверей", "Установщик окон"
]
MACHINERY_TYPES = [
    "Экскаватор", "Бульдозер", "Автокран", "Погрузчик", "Самосвал", "Бетономешалка"
]
TOOL_LIST = [
    "Перфоратор", "Отбойный молоток", "Бетонорез", "Виброплита", "Сварочный аппарат"
]
MATERIAL_TYPES = [
    "Кирпич", "Цемент", "Песок", "Щебень", "Лес/Пиломатериалы", "Металлопрокат", "Изоляция"
]