import sqlalchemy
from sqlalchemy.schema import MetaData

DATABASE_URL = "sqlite:///./app_data.db" # Создаст файл app_data.db в вашей папке

metadata = MetaData()

# Таблица пользователей
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("phone", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("password_hash", sqlalchemy.String),
    sqlalchemy.Column("user_name", sqlalchemy.String),
    sqlalchemy.Column("user_type", sqlalchemy.String),
    sqlalchemy.Column("city", sqlalchemy.String),
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True),
)

# Таблица заявок на работы
work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("specialization", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String),
    sqlalchemy.Column("address", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("city", sqlalchemy.String),
    sqlalchemy.Column("status", sqlalchemy.String),
    sqlalchemy.Column("customer_phone", sqlalchemy.String),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица заявок на спецтехнику
machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("machinery_type", sqlalchemy.String),
    sqlalchemy.Column("address", sqlalchemy.String),
    sqlalchemy.Column("min_order_4h", sqlalchemy.Boolean),
    sqlalchemy.Column("is_preorder", sqlalchemy.Boolean),
    sqlalchemy.Column("preorder_date", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("city", sqlalchemy.String),
    sqlalchemy.Column("status", sqlalchemy.String),
    sqlalchemy.Column("customer_phone", sqlalchemy.String),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица заявок на инструменты
tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("tools_list", sqlalchemy.String),
    sqlalchemy.Column("rent_start_date", sqlalchemy.String),
    sqlalchemy.Column("rent_end_date", sqlalchemy.String),
    sqlalchemy.Column("delivery", sqlalchemy.Boolean),
    sqlalchemy.Column("delivery_address", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("city", sqlalchemy.String),
    sqlalchemy.Column("customer_phone", sqlalchemy.String),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# Таблица объявлений о материалах
material_ads = sqlalchemy.Table(
    "material_ads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("materials", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String),
    sqlalchemy.Column("city", sqlalchemy.String),
    sqlalchemy.Column("seller_phone", sqlalchemy.String),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)
