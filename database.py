import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
import os

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("Переменная окружения DATABASE_URL не установлена. Пожалуйста, установите ее в настройках вашего веб-сервиса на Render.com.")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
metadata = MetaData()

# НОВЫЕ ТАБЛИЦЫ ДЛЯ СПРАВОЧНИКОВ
cities = sqlalchemy.Table(
    "cities",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True)
)

specializations = sqlalchemy.Table(
    "specializations",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True)
)

machinery_types = sqlalchemy.Table(
    "machinery_types",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True)
)

tool_types = sqlalchemy.Table(
    "tool_types",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True)
)

material_types = sqlalchemy.Table(
    "material_types",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True)
)

# ИСПРАВЛЕННЫЕ СУЩЕСТВУЮЩИЕ ТАБЛИЦЫ
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("username", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("password_hash", sqlalchemy.String),
    sqlalchemy.Column("user_name", sqlalchemy.String),
    sqlalchemy.Column("user_type", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("specialization_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("specializations.id"), nullable=True),
)

work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("title", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("specialization_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("specializations.id")),
    sqlalchemy.Column("is_public", sqlalchemy.Boolean, default=True),
    sqlalchemy.Column("is_taken", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True),
)

machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("machinery_type_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("machinery_types.id")),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("tool_type_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("tool_types.id")),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

material_ads = sqlalchemy.Table(
    "material_ads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("material_type_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("material_types.id")),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)