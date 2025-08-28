import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
import os

# Получаем DATABASE_URL из переменных окружения.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Проверяем, что переменная установлена, иначе приложение не запустится
if not DATABASE_URL:
    raise Exception("Переменная окружения DATABASE_URL не установлена. Пожалуйста, установите ее в настройках вашего веб-сервиса на Render.com.")

# ИСПРАВЛЕНИЕ: Render/Heroku дают URL в формате postgres://,
# но SQLAlchemy требует для asyncpg/databases формат postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
metadata = MetaData()

# Таблица пользователей
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("username", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("password_hash", sqlalchemy.String),
    sqlalchemy.Column("user_name", sqlalchemy.String),
    sqlalchemy.Column("user_type", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True),
)

# Таблица заявок на работы
work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("title", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("specialization", sqlalchemy.String),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица заявок на спецтехнику
machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("machinery_type", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица заявок на инструменты (tool_requests)
tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("tool_name", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица объявлений о материалах
material_ads = sqlalchemy.Table(
    "material_ads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("material_type", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)