import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
import os
import databases
from sqlalchemy.types import JSON

# Получаем DATABASE_URL из переменных окружения.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Проверяем, что переменная установлена
if not DATABASE_URL:
    raise ValueError("Переменная окружения DATABASE_URL не установлена.")

# Корректная обработка URL для SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Добавляем параметры SSL, если их нет
if "sslmode" not in DATABASE_URL:
    if "?" in DATABASE_URL:
        DATABASE_URL += "&sslmode=require"
    else:
        DATABASE_URL += "?sslmode=require"

engine = create_engine(DATABASE_URL)
database = databases.Database(DATABASE_URL)
metadata = MetaData()

# Таблица для пользователей
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("hashed_password", sqlalchemy.String),
    sqlalchemy.Column("phone_number", sqlalchemy.String),
    sqlalchemy.Column("is_active", sqlalchemy.Boolean, default=True),
    sqlalchemy.Column("user_type", sqlalchemy.String, nullable=False), # ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id"), nullable=False),
    sqlalchemy.Column("rating", sqlalchemy.Float, nullable=True, default=0.0),
    sqlalchemy.Column("rating_count", sqlalchemy.Integer, nullable=False, default=0)
)

# Таблица заявок на работу
work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("budget", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("phone_number", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("is_taken", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("address", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("visit_date", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False)
)

# Таблица предложений от исполнителей
work_request_offers = sqlalchemy.Table(
    "work_request_offers",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("request_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("work_requests.id")),
    sqlalchemy.Column("performer_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("timestamp", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("status", sqlalchemy.String, default="pending") # 'pending', 'accepted', 'rejected'
)

# Таблица городов
cities = sqlalchemy.Table(
    "cities",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, unique=True, index=True)
)

# Таблица запросов на спецтехнику
machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("machinery_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("rental_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("min_hours", sqlalchemy.Integer, default=4),
)

# Таблица запросов на инструмент
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
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("tool_count", sqlalchemy.Integer, default=1),
    sqlalchemy.Column("rental_start_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("rental_end_date", sqlalchemy.Date, nullable=True),
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
    sqlalchemy.Column("price", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False)
)

# Таблица сообщений чата
chat_messages = sqlalchemy.Table(
    "chat_messages",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("request_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("work_requests.id")),
    sqlalchemy.Column("sender_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("recipient_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")), # Получатель для диалогов 1-на-1
    sqlalchemy.Column("message", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("timestamp", sqlalchemy.DateTime, default=sqlalchemy.func.now())
)