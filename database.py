import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
import os

# Получаем DATABASE_URL из переменных окружения.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Используем локальную базу данных SQLite, если DATABASE_URL не установлена (для быстрого локального запуска)
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./smz_local.db"
    print("ВНИМАНИЕ: DATABASE_URL не установлена. Используется локальная база данных SQLite: ./smz_local.db")

# Замена для работы с SQLite (FastAPI не поддерживает асинхронный SQLite из коробки с databases, но мы оставим структуру для совместимости с postgres/Render)
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

metadata = MetaData()

# Таблица пользователей (users)
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("username", sqlalchemy.String, unique=True, index=True), # Используется для телефона
    sqlalchemy.Column("password_hash", sqlalchemy.String),
    sqlalchemy.Column("user_name", sqlalchemy.String), # Имя пользователя
    sqlalchemy.Column("user_type", sqlalchemy.String), # Тип (ЗАКАЗЧИК, ИСПОЛНИТЕЛЬ, ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ)
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True), # Специализация для ИСПОЛНИТЕЛЬ/ВЛАДЕЛЕЦ
    sqlalchemy.Column("city_id", sqlalchemy.Integer), 
)

# Таблица заявок на работы (work_requests) - Найти мастера
work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("description", sqlalchemy.String),
    sqlalchemy.Column("budget", sqlalchemy.Float), 
    sqlalchemy.Column("contact_info", sqlalchemy.String), 
    sqlalchemy.Column("city_id", sqlalchemy.Integer), 
    sqlalchemy.Column("user_id", sqlalchemy.Integer, nullable=True), 
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица заявок на спецтехнику (machinery_requests) - Аренда спецтехники
machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("machinery_type", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String),
    sqlalchemy.Column("budget", sqlalchemy.Float),
    sqlalchemy.Column("contact_info", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица объявлений о материалах (material_ads) - Продать материалы
material_ads = sqlalchemy.Table(
    "material_ads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("material_type", sqlalchemy.String), 
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("price", sqlalchemy.Float), 
    sqlalchemy.Column("contact_info", sqlalchemy.String), 
    sqlalchemy.Column("city_id", sqlalchemy.Integer), 
    sqlalchemy.Column("user_id", sqlalchemy.Integer, nullable=True), 
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица заявок на инструменты (tool_requests) - Аренда инструмента
tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("tool_name", sqlalchemy.String), 
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float), 
    sqlalchemy.Column("contact_info", sqlalchemy.String), 
    sqlalchemy.Column("city_id", sqlalchemy.Integer), 
    sqlalchemy.Column("user_id", sqlalchemy.Integer, nullable=True), 
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Создаем движок SQLAlchemy с использованием DATABASE_URL
engine = create_engine(DATABASE_URL, connect_args=connect_args if DATABASE_URL.startswith("sqlite") else {})