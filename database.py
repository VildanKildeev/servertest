# file: database.py
import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
from sqlalchemy.sql import func
import os
import databases

# Получаем DATABASE_URL из переменных окружения.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Проверяем, что переменная установлена
if not DATABASE_URL:
    raise Exception("Переменная окружения DATABASE_URL не установлена.")

# АДАПТАЦИЯ URL ДЛЯ RENDER/ASYNC
if "?" in DATABASE_URL:
    if "sslmode" not in DATABASE_URL:
        DATABASE_URL += "&sslmode=require"
else:
    DATABASE_URL += "?sslmode=require"

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
database = databases.Database(DATABASE_URL)
metadata = MetaData()

# =======================================================================
# НОВАЯ ТАБЛИЦА: 1. Справочник специализаций (Specializations)
# =======================================================================
specializations = sqlalchemy.Table(
    "specializations",
    metadata,
    sqlalchemy.Column("code", sqlalchemy.String, primary_key=True), # Уникальный код, например "electrician"
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False, unique=True), # Человекочитаемое имя, "Электрик"
)

# =======================================================================
# 2. Таблица городов (Cities) - БЕЗ ИЗМЕНЕНИЙ
# =======================================================================
cities = sqlalchemy.Table(
    "cities",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False, unique=True),
)

# =======================================================================
# 3. Таблица пользователей (Users) - ИЗМЕНЕНА
# =======================================================================
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String, nullable=False, unique=True),
    sqlalchemy.Column("hashed_password", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("phone_number", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("user_type", sqlalchemy.String, default="ЗАКАЗЧИК"), # ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ
    # Поле оставлено для обратной совместимости, будет "зеркалом" основной специализации
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False, server_default="false", nullable=False),
    # НОВОЕ ПОЛЕ: Дата окончания премиум подписки
    sqlalchemy.Column("premium_until", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("average_rating", sqlalchemy.Float, nullable=False, default=0.0, server_default="0.0"),
    sqlalchemy.Column("ratings_count", sqlalchemy.Integer, nullable=False, default=0, server_default="0"),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
)

# =======================================================================
# НОВАЯ ТАБЛИЦА: 4. Специализации исполнителей (Performer Specializations)
# =======================================================================
performer_specializations = sqlalchemy.Table(
    "performer_specializations",
    metadata,
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), primary_key=True),
    sqlalchemy.Column("specialization_code", sqlalchemy.String, sqlalchemy.ForeignKey("specializations.code"), primary_key=True),
    sqlalchemy.Column("is_primary", sqlalchemy.Boolean, default=False, nullable=False),
)

# =======================================================================
# 5. Таблица заявок на работу (Work Requests) - БЕЗ ИЗМЕНЕНИЙ
# =======================================================================
work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=False),
    # ВАЖНО: Это поле должно содержать имя специализации (name), а не код (code)
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("budget", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True),
    sqlalchemy.Column("status", sqlalchemy.String, default="ОЖИДАЕТ"),
    sqlalchemy.Column("is_master_visit_required", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
)

# =======================================================================
# 6. Таблица откликов на заявки (Work Request Responses) - БЕЗ ИЗМЕНЕНИЙ
# =======================================================================
work_request_responses = sqlalchemy.Table(
    "work_request_responses",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("work_request_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("work_requests.id"), nullable=False),
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
    sqlalchemy.Column("comment", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("status", sqlalchemy.String, default="PENDING"),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    sqlalchemy.UniqueConstraint('work_request_id', 'executor_id', name='uq_work_request_executor'),
)

# =======================================================================
# 7. Таблица оценок (Ratings) - БЕЗ ИЗМЕНЕНИЙ
# =======================================================================
ratings = sqlalchemy.Table(
    "ratings",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("work_request_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("work_requests.id"), nullable=False),
    sqlalchemy.Column("rater_user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
    sqlalchemy.Column("rated_user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
    sqlalchemy.Column("rating_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("rating", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("comment", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    sqlalchemy.UniqueConstraint('rater_user_id', 'rated_user_id', 'work_request_id', name='uq_rating_per_request'),
)

# --- Остальные таблицы без изменений ---

machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("machinery_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True),
    sqlalchemy.Column("status", sqlalchemy.String, default="ОЖИДАЕТ"),
    sqlalchemy.Column("rental_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("min_rental_hours", sqlalchemy.Integer, default=4, nullable=False),
    sqlalchemy.Column("has_delivery", sqlalchemy.Boolean, default=False, nullable=False),
    sqlalchemy.Column("delivery_address", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
)

tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("tool_name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("rental_price", sqlalchemy.Float, nullable=False),
    sqlalchemy.Column("contact_info", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("city_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("cities.id")),
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True),
    sqlalchemy.Column("status", sqlalchemy.String, default="ОЖИДАЕТ"),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    sqlalchemy.Column("count", sqlalchemy.Integer, default=1),
    sqlalchemy.Column("rental_start_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("rental_end_date", sqlalchemy.Date, nullable=True),
    sqlalchemy.Column("has_delivery", sqlalchemy.Boolean, default=False, nullable=False),
    sqlalchemy.Column("delivery_address", sqlalchemy.String, nullable=True),
)

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
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
)

# Функция для создания всех таблиц в базе данных
def create_db_tables():
    print("Creating database tables...")
    metadata.create_all(engine)
    print("Tables created.")