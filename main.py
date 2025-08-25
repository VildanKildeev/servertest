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

class UserInDB(UserCreate):
    id: int

class WorkRequestCreate(BaseModel):
    description: str
    budget: float
    contact_info: str
    city_id: int
    specialization: str
    user_id: int

class WorkRequestInDB(WorkRequestCreate):
    id: int
    created_at: datetime

class MachineryRequestCreate(BaseModel):
    machine_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    user_id: int

class MachineryRequestInDB(MachineryRequestCreate):
    id: int
    created_at: datetime

class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    user_id: int

class ToolRequestInDB(ToolRequestCreate):
    id: int
    created_at: datetime

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int
    user_id: int

class MaterialAdInDB(MaterialAdCreate):
    id: int
    created_at: datetime

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
    return {**user.model_dump(), "id": last_record_id, "password_hash": hashed_password}

@api_router.post("/login")
async def login_user(username: str, password: str):
    query = users.select().where(users.c.username == username)
    user_record = await database.fetch_one(query)
    if not user_record or not verify_password(password, user_record["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    fake_token = f"fake_token_{user_record['id']}"
    return {"token": fake_token, "user": dict(user_record)}

@api_router.get("/user/me")
async def read_current_user(user_id: int = Depends(fake_auth)):
    query = users.select().where(users.c.id == user_id)
    user_record = await database.fetch_one(query)
    if not user_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return dict(user_record)

@api_router.post("/work-requests", response_model=WorkRequestInDB, status_code=status.HTTP_201_CREATED)
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
    return {**request.model_dump(), "id": last_record_id, "user_id": user_id, "created_at": datetime.now()}

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def read_work_requests(city_id: Optional[int] = None):
    query = work_requests.select()
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return requests

@api_router.post("/machinery-requests", response_model=MachineryRequestInDB, status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestCreate, user_id: int = Depends(fake_auth)):
    query = machinery_requests.insert().values(
        machine_type=request.machine_type,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id,
        user_id=user_id
    )
    last_record_id = await database.execute(query)
    return {**request.model_dump(), "id": last_record_id, "user_id": user_id, "created_at": datetime.now()}

@api_router.get("/machinery-requests", response_model=List[MachineryRequestInDB])
async def read_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select()
    if city_id is not None:
        query = query.where(machinery_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return requests

@api_router.post("/tool-requests", response_model=ToolRequestInDB, status_code=status.HTTP_201_CREATED)
async def create_tool_request(request: ToolRequestCreate, user_id: int = Depends(fake_auth)):
    query = tool_requests.insert().values(
        tool_name=request.tool_name,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id,
        user_id=user_id
    )
    last_record_id = await database.execute(query)
    return {**request.model_dump(), "id": last_record_id, "user_id": user_id, "created_at": datetime.now()}

@api_router.get("/tool-requests", response_model=List[ToolRequestInDB])
async def read_tool_requests(city_id: Optional[int] = None):
    query = tool_requests.select()
    if city_id is not None:
        query = query.where(tool_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return requests

@api_router.post("/material-ads", response_model=MaterialAdInDB, status_code=status.HTTP_201_CREATED)
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
    return {**ad.model_dump(), "id": last_record_id, "user_id": user_id, "created_at": datetime.now()}

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
        "Отделочник", "Сантехник", "Электрик", "Плотник",
        "Сварщик", "Каменщик", "Маляр", "Кровельщик",
        "Разнорабочий", "Другое"
    ]
    return specializations

app.include_router(api_router)

# Статические файлы (должен быть в конце, после API маршрутов)
# Теперь ищет index.html в корневом каталоге, который вы должны создать.
app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)