Я понимаю, что вы используете city_id для связи с городами, и простое удаление этой колонки кажется неправильным. Ваше беспокойство обосновано.

Проблема не в том, что вам не нужна ссылка на город, а в том, как эта ссылка реализована. Согласно правилам баз данных, внешний ключ (FOREIGN KEY) может ссылаться только на первичный ключ (PRIMARY KEY) или на колонку с уникальным ограничением (UNIQUE). Колонка city_id в таблице users не является уникальной (так как много пользователей могут быть из одного города), что и вызывает ошибку.

Идеальное решение: отдельная таблица для городов

Чтобы правильно связать города с пользователями и заявками, нужно создать отдельную таблицу cities, которая будет хранить информацию о городах. Это лучшая практика в проектировании баз данных.

    Создайте таблицу cities с уникальным идентификатором (id) и названием города (name).

    Добавьте FOREIGN KEY из таблицы users на id в таблице cities.

    Добавьте FOREIGN KEY из таблиц заявок (work_requests, machinery_requests и т.д.) на id в таблице cities.

Обновленный main.py

Для решения проблемы замените определения ваших таблиц в файле main.py на предоставленный ниже код. Я добавил новую таблицу cities и обновил все другие таблицы, чтобы они ссылались на неё.
Python

import json
import uvicorn
import databases
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy import exc, Column, Integer, String, Float, Boolean, ForeignKey, Table, DateTime, MetaData, Date, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy import create_engine

import os
from dotenv import load_dotenv
load_dotenv()

# --- Database setup ---
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@host:port/dbname")

metadata = MetaData()

cities = Table(
    "cities",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, unique=True, nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String, unique=True, nullable=False),
    Column("password_hash", String, nullable=False),
    Column("user_name", String),
    Column("user_type", String),
    Column("city_id", Integer, ForeignKey("cities.id")),
    Column("specialization", String, nullable=True),
    Column("is_premium", Boolean, default=False, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
)

work_requests = Table(
    "work_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("description", String, nullable=False),
    Column("budget", Float),
    Column("contact_info", String),
    Column("city_id", Integer, ForeignKey("cities.id")),
    Column("specialization", String, nullable=False),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("executor_id", Integer, ForeignKey("users.id"), nullable=True),
    Column("is_premium", Boolean, default=False, nullable=False),
)

machinery_requests = Table(
    "machinery_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("machinery_type", String, nullable=False),
    Column("description", String),
    Column("rental_price", Float),
    Column("contact_info", String),
    Column("city_id", Integer, ForeignKey("cities.id")),
    Column("created_at", DateTime, default=datetime.utcnow),
)

tool_requests = Table(
    "tool_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("tool_name", String, nullable=False),
    Column("description", String),
    Column("rental_price", Float),
    Column("contact_info", String),
    Column("count", Integer),
    Column("rental_start_date", Date),
    Column("rental_end_date", Date),
    Column("city_id", Integer, ForeignKey("cities.id")),
    Column("created_at", DateTime, default=datetime.utcnow),
)

material_ads = Table(
    "material_ads",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("material_type", String, nullable=False),
    Column("description", String),
    Column("price", Float),
    Column("contact_info", String),
    Column("city_id", Integer, ForeignKey("cities.id")),
    Column("created_at", DateTime, default=datetime.utcnow),
)

database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

app = FastAPI(title="СМЗ.РФ API")

api_router = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    engine = create_engine(DATABASE_URL)
    metadata.create_all(engine)
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# =======================================================
#               МОДЕЛИ Pydantic
# =======================================================

class UserBase(BaseModel):
    username: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False

class UserCreate(UserBase):
    password: str

class UserPublic(UserBase):
    id: int
    created_at: Optional[datetime] = None

class UserInDB(UserBase):
    id: int
    password_hash: str
    created_at: Optional[datetime] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class WorkRequestCreate(BaseModel):
    description: str
    budget: float
    contact_info: str
    specialization: Optional[str] = None
    
class WorkRequestInDB(WorkRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    executor_id: Optional[int] = None
    city_id: int
    is_premium: Optional[bool] = False

class MachineryRequestCreate(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    
class MachineryRequestInDB(MachineryRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    city_id: int

class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    count: Optional[int] = None
    rental_start_date: Optional[date] = None
    rental_end_date: Optional[date] = None

class ToolRequestInDB(ToolRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    city_id: int

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: Optional[str] = None

class MaterialAdInDB(MaterialAdCreate):
    id: int
    user_id: int
    created_at: datetime
    city_id: int

class MyRequestsResponse(BaseModel):
    work_requests: List[WorkRequestInDB]
    machinery_requests: List[MachineryRequestInDB]
    tool_requests: List[ToolRequestInDB]
    material_ads: List[MaterialAdInDB]

# =======================================================
#               ФУНКЦИИ АУТЕНТИФИКАЦИИ
# =======================================================

from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    if user is None:
        raise credentials_exception
    return UserInDB(**user._mapping)

# =======================================================
#               ОБЩИЕ ФУНКЦИИ
# =======================================================

async def create_record_and_return(table, data_to_insert, response_model, current_user=None):
    if current_user:
        data_to_insert["user_id"] = current_user.id
        data_to_insert["city_id"] = current_user.city_id
    
    if "rental_start_date" in data_to_insert and isinstance(data_to_insert["rental_start_date"], str):
        data_to_insert["rental_start_date"] = datetime.strptime(data_to_insert["rental_start_date"], '%Y-%m-%d').date()
    if "rental_end_date" in data_to_insert and isinstance(data_to_insert["rental_end_date"], str):
        data_to_insert["rental_end_date"] = datetime.strptime(data_to_insert["rental_end_date"], '%Y-%m-%d').date()

    try:
        query = table.insert().values(**data_to_insert)
        last_record_id = await database.execute(query)
        new_record_data = {
            "id": last_record_id,
            "created_at": datetime.now(),
            **data_to_insert
        }
        return response_model(**new_record_data)
    except exc.IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при создании записи: {str(e)}")

# =======================================================
#               МАРШРУТЫ API
# =======================================================

@api_router.get("/create-tables")
async def create_tables():
    try:
        engine = create_engine(DATABASE_URL)
        metadata.create_all(engine)
        return {"message": "Таблицы успешно созданы."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при создании таблиц: {str(e)}")

@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    query = users.select().where(users.c.username == form_data.username)
    user = await database.fetch_one(query)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.post("/users/", response_model=UserPublic)
async def create_user(user: UserCreate):
    if await database.fetch_one(users.select().where(users.c.username == user.username)):
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = get_password_hash(user.password)
    data_to_insert = {
        "username": user.username,
        "password_hash": hashed_password,
        "user_name": user.user_name,
        "user_type": user.user_type,
        "city_id": user.city_id,
        "specialization": user.specialization,
        "is_premium": user.is_premium
    }
    
    return await create_record_and_return(
        table=users,
        data_to_insert=data_to_insert,
        response_model=UserPublic
    )

@api_router.get("/users/me", response_model=UserPublic)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    user_data = current_user.model_dump()
    return UserPublic(**user_data)

@api_router.put("/users/update-specialization")
async def update_user_specialization(specialization: str, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только Исполнители могут обновлять специализацию.")

    query = users.update().where(users.c.id == current_user.id).values(specialization=specialization)
    await database.execute(query)
    return {"message": "Специализация успешно обновлена."}

@api_router.post("/subscribe")
async def subscribe_user(current_user: UserInDB = Depends(get_current_user)):
    if current_user.is_premium:
        raise HTTPException(status_code=400, detail="У вас уже есть премиум-подписка.")
    
    query = users.update().where(users.c.id == current_user.id).values(is_premium=True)
    await database.execute(query)
    
    return {"message": "Премиум-подписка успешно активирована!"}

@api_router.get("/users/my-requests", response_model=MyRequestsResponse)
async def read_my_requests(current_user: UserInDB = Depends(get_current_user)):
    work_query = work_requests.select().where(work_requests.c.user_id == current_user.id)
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == current_user.id)
    tool_query = tool_requests.select().where(tool_requests.c.user_id == current_user.id)
    material_query = material_ads.select().where(material_ads.c.user_id == current_user.id)
    
    work_results = await database.fetch_all(work_query)
    machinery_results = await database.fetch_all(machinery_query)
    tool_results = await database.fetch_all(tool_query)
    material_results = await database.fetch_all(material_query)
    
    return {
        "work_requests": [WorkRequestInDB(**r._mapping) for r in work_results],
        "machinery_requests": [MachineryRequestInDB(**r._mapping) for r in machinery_results],
        "tool_requests": [ToolRequestInDB(**r._mapping) for r in tool_results],
        "material_ads": [MaterialAdInDB(**r._mapping) for r in material_results],
    }

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(request: WorkRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    if not request.specialization:
        raise HTTPException(status_code=400, detail="Специализация не может быть пустой.")
    
    data_to_insert = request.model_dump()
    data_to_insert["is_premium"] = current_user.is_premium
    
    return await create_record_and_return(
        table=work_requests,
        data_to_insert=data_to_insert,
        response_model=WorkRequestInDB,
        current_user=current_user
    )

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def read_work_requests(city_id: Optional[int] = None):
    query = work_requests.select().where(work_requests.c.executor_id.is_(None))
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    
    requests = await database.fetch_all(query.order_by(work_requests.c.is_premium.desc()))
    return [WorkRequestInDB(**r._mapping) for r in requests]

@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(request: MachineryRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    data_to_insert = request.model_dump()
    return await create_record_and_return(
        table=machinery_requests,
        data_to_insert=data_to_insert,
        response_model=MachineryRequestInDB,
        current_user=current_user
    )

@api_router.get("/machinery-requests", response_model=List[MachineryRequestInDB])
async def read_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select()
    if city_id is not None:
        query = query.where(machinery_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [MachineryRequestInDB(**r._mapping) for r in requests]

@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(request: ToolRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    data_to_insert = request.model_dump()
    if data_to_insert.get("rental_start_date"):
        data_to_insert["rental_start_date"] = date.fromisoformat(str(data_to_insert["rental_start_date"]))
    if data_to_insert.get("rental_end_date"):
        data_to_insert["rental_end_date"] = date.fromisoformat(str(data_to_insert["rental_end_date"]))
    
    return await create_record_and_return(
        table=tool_requests,
        data_to_insert=data_to_insert,
        response_model=ToolRequestInDB,
        current_user=current_user
    )

@api_router.get("/tool-requests", response_model=List[ToolRequestInDB])
async def read_tool_requests(city_id: Optional[int] = None):
    query = tool_requests.select()
    if city_id is not None:
        query = query.where(tool_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [ToolRequestInDB(**r._mapping) for r in requests]

@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(ad: MaterialAdCreate, current_user: UserInDB = Depends(get_current_user)):
    data_to_insert = ad.model_dump()
    return await create_record_and_return(
        table=material_ads,
        data_to_insert=data_to_insert,
        response_model=MaterialAdInDB,
        current_user=current_user
    )

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def read_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id is not None:
        query = query.where(material_ads.c.city_id == city_id)
    ads = await database.fetch_all(query)
    return [MaterialAdInDB(**r._mapping) for r in ads]

@api_router.post("/work-requests/{request_id}/accept", response_model=WorkRequestInDB)
async def accept_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только Исполнители могут принимать заявки.")

    if not current_user.specialization:
        raise HTTPException(status_code=400, detail="Для принятия заявки необходимо указать вашу специализацию.")

    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)

    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    return WorkRequestInDB(**request._mapping)

@api_router.get("/cities")
async def get_cities():
    cities = [\
        {"id": 1, "name": "Москва"},
        {"id": 2, "name": "Санкт-Петербург"},
        {"id": 3, "name": "Казань"},
        {"id": 4, "name": "Екатеринбург"},
        {"id": 5, "name": "Новосибирск"},
    ]
    return cities

@api_router.get("/specializations")
async def get_specializations():
    specializations = [\
        "Отделочник", "Сантехник", "Электрик", "Мастер по мебели", "Мастер на час", "Уборка", "Проектирование"\
    ]
    return specializations

@api_router.get("/machinery-types")
async def get_machinery_types():
    machinery_types = [\
        "Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Грейдер", "Погрузчик", "Каток", "Трактор", "Миксер"\
    ]
    return machinery_types

@api_router.get("/tools-list")
async def get_tools_list():
    tools_list = [\
        "Перфоратор", "Шуруповерт", "Болгарка", "Сварочный аппарат", "Бетономешалка", "Лазерный уровень", "Строительный пылесос", "Компрессор", "Отбойный молоток"\
    ]
    return tools_list

app.include_router(api_router)

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return HTMLResponse(content=open("index.html", "r").read(), status_code=200)
    
app.include_router(api_router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")