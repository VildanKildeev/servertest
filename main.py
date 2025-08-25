Конечно, вот полный код файла main.py, включающий все исправления для корректной работы вашего сервера и устранения ошибки FileNotFoundError.

Я добавил использование модуля os для правильного определения пути к файлам, чтобы приложение работало на любой платформе.
Python

import json
import uvicorn
import databases
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

import os
from dotenv import load_dotenv
load_dotenv()

from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL

# Определяем базовую директорию (папка, где находится main.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
    # Создаем таблицы, если их нет
    metadata.create_all(engine)
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

class UserCreate(BaseModel):
    username: str
    password: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class UserInDB(BaseModel):
    id: int
    username: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class WorkRequestCreate(BaseModel):
    description: str
    contact_info: str
    city_id: int
    specialization: str
    budget: Optional[float] = None
    photos: Optional[List[str]] = []

class WorkRequestInDB(WorkRequestCreate):
    id: int
    user_id: int
    created_at: datetime

class MachineryRequestCreate(BaseModel):
    machine_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    is_preorder: bool
    preorder_date: Optional[datetime] = None
    photos: Optional[List[str]] = []

class MachineryRequestInDB(MachineryRequestCreate):
    id: int
    user_id: int
    created_at: datetime

class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    start_date: datetime
    end_date: datetime
    delivery_needed: bool
    delivery_address: Optional[str] = None
    photos: Optional[List[str]] = []

class ToolRequestInDB(ToolRequestCreate):
    id: int
    user_id: int
    created_at: datetime

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int
    photos: Optional[List[str]] = []

class MaterialAdInDB(MaterialAdCreate):
    id: int
    user_id: int
    created_at: datetime

class UserAuth(BaseModel):
    username: str
    password: str

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def fake_auth(token: str = Depends(lambda t: t.headers.get("Authorization"))):
    if token is None or not token.startswith("Bearer fake_token_"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен")
    try:
        user_id = int(token.split("_")[-1])
        return user_id
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный формат токена")

@api_router.post("/register", response_model=UserInDB, status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate):
    query = users.select().where(users.c.username == user.username)
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пользователь с таким логином уже существует.")
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization
    )
    last_record_id = await database.execute(query)
    return {**user.model_dump(), "id": last_record_id}

@api_router.post("/login")
async def login_user(user_auth: UserAuth):
    query = users.select().where(users.c.username == user_auth.username)
    user_record = await database.fetch_one(query)
    if not user_record or not verify_password(user_auth.password, user_record["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    fake_token = f"fake_token_{user_record['id']}"
    return {"token": fake_token, "user": dict(user_record)}

@api_router.get("/user/me", response_model=UserInDB)
async def read_current_user(user_id: int = Depends(fake_auth)):
    query = users.select().where(users.c.id == user_id)
    user_record = await database.fetch_one(query)
    if not user_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return dict(user_record)

@api_router.post("/work-requests", status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestCreate, user_id: int = Depends(fake_auth)):
    query = work_requests.insert().values(
        description=request.description,
        budget=request.budget,
        contact_info=request.contact_info,
        city_id=request.city_id,
        specialization=request.specialization,
        user_id=user_id
    )
    last_record_id = await database.execute(query)
    return {"message": "Заявка успешно создана!", "id": last_record_id}

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def read_work_requests(city_id: Optional[int] = None, specialization: Optional[str] = None):
    query = work_requests.select()
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    if specialization is not None:
        query = query.where(work_requests.c.specialization == specialization)
    requests = await database.fetch_all(query)
    return requests

@api_router.get("/my-work-requests", response_model=List[WorkRequestInDB])
async def read_my_work_requests(user_id: int = Depends(fake_auth)):
    query = work_requests.select().where(work_requests.c.user_id == user_id)
    requests = await database.fetch_all(query)
    return requests

@api_router.post("/machinery-requests", status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestCreate, user_id: int = Depends(fake_auth)):
    query = machinery_requests.insert().values(
        machine_type=request.machine_type,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id,
        user_id=user_id,
        is_preorder=request.is_preorder,
        preorder_date=request.preorder_date
    )
    last_record_id = await database.execute(query)
    return {"message": "Заявка успешно создана!", "id": last_record_id}

@api_router.post("/tool-requests", status_code=status.HTTP_201_CREATED)
async def create_tool_request(request: ToolRequestCreate, user_id: int = Depends(fake_auth)):
    query = tool_requests.insert().values(
        tool_name=request.tool_name,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id,
        user_id=user_id,
        start_date=request.start_date,
        end_date=request.end_date,
        delivery_needed=request.delivery_needed,
        delivery_address=request.delivery_address
    )
    last_record_id = await database.execute(query)
    return {"message": "Заявка успешно создана!", "id": last_record_id}

@api_router.post("/material-ads", status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad: MaterialAdCreate, user_id: int = Depends(fake_auth)):
    query = material_ads.insert().values(
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        contact_info=ad.contact_info,
        city_id=ad.city_id,
        user_id=user_id
    )
    last_record_id = await database.execute(query)
    return {"message": "Объявление успешно создано!", "id": last_record_id}

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def read_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id is not None:
        query = query.where(material_ads.c.city_id == city_id)
    ads = await database.fetch_all(query)
    return ads

@api_router.get("/cities")
async def get_cities():
    cities = [
        {"id": 1, "name": "Москва"},
        {"id": 2, "name": "Санкт-Петербург"},
        {"id": 3, "name": "Казань"},
        {"id": 4, "name": "Екатеринбург"},
        {"id": 5, "name": "Новосибирск"},
    ]
    return cities

@api_router.get("/specializations")
async def get_specializations():
    specializations = [
        "Отделочник", "Сантехник", "Электрик", "Плотник", "Мастер на час", "Сварщик", "Кровельщик",
        "Маляр", "Грузчик", "Строитель", "Водитель спецтехники"
    ]
    return specializations

# Добавляем маршрутизатор API к основному приложению
app.include_router(api_router)

# Обслуживание статических файлов
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

# Роут для главной страницы
@app.get("/")
async def serve_root():
    index_path = os.path.join(BASE_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# Роут для отдачи index.html для любого пути, чтобы работал одностраничный режим
@app.get("/{full_path:path}")
async def serve_index(full_path: str):
    index_path = os.path.join(BASE_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())