import json
import uvicorn
import databases
from jose import jwt, JWTError
from datetime import timedelta
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
    metadata.create_all(engine)
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

async def authenticate_user(username, password):
    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    if not user:
        return False
    if not verify_password(password, user.password_hash):
        return False
    return user

async def get_current_user(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")
    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user

async def get_current_active_user(current_user: users = Depends(get_current_user)):
    return current_user

class UserIn(BaseModel):
    username: str
    password: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    username: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class WorkRequestIn(BaseModel):
    title: str
    description: Optional[str] = None
    city_id: int
    specialization: str

class WorkRequestInDB(BaseModel):
    id: int
    title: str
    description: Optional[str]
    city_id: int
    specialization: str
    user_id: int
    created_at: datetime
    executor_id: Optional[int]

class WorkRequestUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    city_id: Optional[int] = None
    specialization: Optional[str] = None

class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class MachineryRequestInDB(BaseModel):
    id: int
    machinery_type: str
    description: Optional[str]
    rental_price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime

class ToolRequestIn(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class ToolRequestInDB(BaseModel):
    id: int
    tool_name: str
    description: Optional[str]
    rental_price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime

class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

class MaterialAdInDB(BaseModel):
    id: int
    material_type: str
    description: Optional[str]
    price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime

@api_router.post("/register")
async def register(user: UserIn):
    query = users.select().where(users.c.username == user.username)
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(status_code=400, detail="Имя пользователя уже существует")

    password_hash = get_password_hash(user.password)
    insert_query = users.insert().values(username=user.username, password_hash=password_hash, user_name=user.user_name, user_type=user.user_type, city_id=user.city_id, specialization=user.specialization)
    await database.execute(insert_query)
    return {"message": "Пользователь успешно зарегистрирован."}

@api_router.post("/token", response_model=Token)
async def login_for_access_token(user_in: UserIn):
    user = await authenticate_user(user_in.username, user_in.password)
    if not user:
        raise HTTPException(status_code=400, detail="Неверное имя пользователя или пароль")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "user_id": user.id, "user_type": user.user_type, "city_id": user.city_id},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.id, "username": user.username, "user_name": user.user_name, "user_type": user.user_type, "city_id": user.city_id, "specialization": user.specialization}

@api_router.get("/users/me")
async def read_users_me(current_user: users = Depends(get_current_active_user)):
    return current_user

@api_router.get("/profile/{user_id}")
async def get_user_profile(user_id: int):
    query = users.select().where(users.c.id == user_id)
    user = await database.fetch_one(query)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user

@api_router.post("/work-requests", status_code=status.HTTP_201_CREATED)
async def create_work_request(work_request: WorkRequestIn, current_user: users = Depends(get_current_active_user)):
    if current_user.user_type != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только заказчики могут создавать заявки на работы.")
    
    query = work_requests.insert().values(
        title=work_request.title,
        description=work_request.description,
        city_id=work_request.city_id,
        specialization=work_request.specialization,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **work_request.dict(), "user_id": current_user.id}

@api_router.get("/work-requests")
async def get_work_requests(city_id: Optional[int] = None):
    query = work_requests.select()
    if city_id:
        query = query.where(work_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [WorkRequestInDB(**r._mapping) for r in requests]

@api_router.get("/work-requests/{request_id}")
async def get_work_request(request_id: int):
    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return WorkRequestInDB(**request._mapping)

@api_router.post("/work-requests/{request_id}/take", response_model=WorkRequestInDB)
async def take_work_request(request_id: int, current_user: users = Depends(get_current_active_user)):
    if current_user.user_type not in ["ИСПОЛНИТЕЛЬ", "ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ"]:
        raise HTTPException(status_code=403, detail="Только исполнители могут принимать заявки.")

    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    updated_request_query = work_requests.select().where(work_requests.c.id == request_id)
    updated_request = await database.fetch_one(updated_request_query)

    return WorkRequestInDB(**updated_request._mapping)

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
        "Отделочник", "Сантехник", "Электрик", "Мастер по мебели", "Мастер на час", "Уборка", "Проектирование"
    ]
    return specializations

@api_router.get("/machinery-types")
async def get_machinery_types():
    machinery_types = [
        "Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Ямобур", "Манипулятор", "Погрузчик", "Эвакуатор"
    ]
    return machinery_types

@api_router.get("/tool-types")
async def get_tool_types():
    tool_types = [
        "Отбойный молоток", "Вибратор для бетона", "Компрессор", "Сварочный аппарат", "Генератор", "Бетономешалка"
    ]
    return tool_types

@api_router.get("/material-types")
async def get_material_types():
    material_types = [
        "Кирпич", "Бетон", "Дерево", "Металл", "Плитка", "Гипсокартон"
    ]
    return material_types

@api_router.post("/machinery-requests", status_code=status.HTTP_201_CREATED)
async def create_machinery_request(machinery_request: MachineryRequestIn, current_user: users = Depends(get_current_active_user)):
    if current_user.user_type != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только заказчики могут создавать заявки на спецтехнику.")

    query = machinery_requests.insert().values(
        machinery_type=machinery_request.machinery_type,
        description=machinery_request.description,
        rental_price=machinery_request.rental_price,
        contact_info=machinery_request.contact_info,
        city_id=machinery_request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **machinery_request.dict(), "user_id": current_user.id}

@api_router.get("/machinery-requests")
async def get_machinery_requests(city_id: Optional[int] = None, machinery_type: Optional[str] = None):
    query = machinery_requests.select()
    if city_id:
        query = query.where(machinery_requests.c.city_id == city_id)
    if machinery_type:
        query = query.where(machinery_requests.c.machinery_type == machinery_type)
    requests = await database.fetch_all(query)
    return [MachineryRequestInDB(**r._mapping) for r in requests]

@api_router.post("/tool-requests", status_code=status.HTTP_201_CREATED)
async def create_tool_request(tool_request: ToolRequestIn, current_user: users = Depends(get_current_active_user)):
    if current_user.user_type != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только заказчики могут создавать заявки на инструменты.")
        
    query = tool_requests.insert().values(
        tool_name=tool_request.tool_name,
        description=tool_request.description,
        rental_price=tool_request.rental_price,
        contact_info=tool_request.contact_info,
        city_id=tool_request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **tool_request.dict(), "user_id": current_user.id}

@api_router.get("/tool-requests")
async def get_tool_requests(city_id: Optional[int] = None, tool_name: Optional[str] = None):
    query = tool_requests.select()
    if city_id:
        query = query.where(tool_requests.c.city_id == city_id)
    if tool_name:
        query = query.where(tool_requests.c.tool_name == tool_name)
    requests = await database.fetch_all(query)
    return [ToolRequestInDB(**r._mapping) for r in requests]

@api_router.post("/material-ads", status_code=status.HTTP_201_CREATED)
async def create_material_ad(material_ad: MaterialAdIn, current_user: users = Depends(get_current_active_user)):
    if current_user.user_type != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только заказчики могут создавать объявления о материалах.")
        
    query = material_ads.insert().values(
        material_type=material_ad.material_type,
        description=material_ad.description,
        price=material_ad.price,
        contact_info=material_ad.contact_info,
        city_id=material_ad.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **material_ad.dict(), "user_id": current_user.id}

@api_router.get("/material-ads")
async def get_material_ads(city_id: Optional[int] = None, material_type: Optional[str] = None):
    query = material_ads.select()
    if city_id:
        query = query.where(material_ads.c.city_id == city_id)
    if material_type:
        query = query.where(material_ads.c.material_type == material_type)
    ads = await database.fetch_all(query)
    return [MaterialAdInDB(**ad._mapping) for ad in ads]

app.include_router(api_router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")