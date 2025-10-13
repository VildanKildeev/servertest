import sqlalchemy
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
from sqlalchemy.sql import func
import os
import databases
from sqlalchemy.types import JSON
from sqlalchemy.sql import func 

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
# 1. Таблица городов (Cities) - БЕЗ ИЗМЕНЕНИЙ
# =======================================================================
cities = sqlalchemy.Table(
    "cities",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False, unique=True),
)

# =======================================================================
# 2. Таблица пользователей (Users) - ИЗМЕНЕНА
# =======================================================================
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String, nullable=False, unique=True),
    sqlalchemy.Column("hashed_password", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("phone_number", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("user_type", sqlalchemy.String, default="ЗАКАЗЧИК"), # ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("is_premium", sqlalchemy.Boolean, default=False),
    # ИЗМЕНЕНО: Поля для рейтинга теперь не имеют значения по умолчанию в БД,
    # так как они будут вычисляться. В модели Pydantic мы можем задать default.
    sqlalchemy.Column("average_rating", sqlalchemy.Float, nullable=False, default=0.0, server_default="0.0"),
    sqlalchemy.Column("ratings_count", sqlalchemy.Integer, nullable=False, default=0, server_default="0"),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
)

# =======================================================================
# 3. Таблица заявок на работу (Work Requests) - ИЗМЕНЕНА
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
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=True),
    # ИЗМЕНЕНО: Четкая система статусов
    sqlalchemy.Column("status", sqlalchemy.String, default="ОЖИДАЕТ"), # ОЖИДАЕТ, В РАБОТЕ, ВЫПОЛНЕНА, ОТМЕНЕНА
    sqlalchemy.Column("is_master_visit_required", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
)

# =======================================================================
# 4. НОВАЯ ТАБЛИЦА: Отклики на заявки (Work Request Responses)
# =======================================================================
work_request_responses = sqlalchemy.Table(
    "work_request_responses",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("work_request_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("work_requests.id"), nullable=False),
    sqlalchemy.Column("executor_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False), # Исполнитель, который откликнулся
    sqlalchemy.Column("comment", sqlalchemy.String, nullable=True), # Комментарий от исполнителя к отклику
    sqlalchemy.Column("status", sqlalchemy.String, default="PENDING"), # PENDING, APPROVED, REJECTED
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    # Уникальное ограничение, чтобы один исполнитель не мог откликнуться дважды на одну заявку
    sqlalchemy.UniqueConstraint('work_request_id', 'executor_id', name='uq_work_request_executor'),
)

# =======================================================================
# 5. Таблица оценок (Ratings) - ПОЛНОСТЬЮ ПЕРЕРАБОТАНА
# =======================================================================
ratings = sqlalchemy.Table(
    "ratings",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("work_request_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("work_requests.id"), nullable=False),
    # Пользователь, КОТОРЫЙ ставит оценку
    sqlalchemy.Column("rater_user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
    # Пользователь, КОТОРОМУ ставят оценку
    sqlalchemy.Column("rated_user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
    # Тип оценки: 'TO_EXECUTOR' (Заказчик -> Исполнителю) или 'TO_CUSTOMER' (Исполнитель -> Заказчику)
    sqlalchemy.Column("rating_type", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("rating", sqlalchemy.Integer, nullable=False), # Оценка от 1 до 5
    sqlalchemy.Column("comment", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=func.now()),
    # Уникальное ограничение: один пользователь не может оценить другого за одну и ту же заявку дважды
    sqlalchemy.UniqueConstraint('rater_user_id', 'rated_user_id', 'work_request_id', name='uq_rating_per_request'),
)

# --- Остальные таблицы без критических изменений для основной логики ---

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
    metadata.create_all(engine)