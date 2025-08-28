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
from fastapi.security import OAuth2PasswordBearer # <-- Добавлено

import os
from dotenv import load_dotenv
load_dotenv()

from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL

database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Модели Pydantic для данных
class UserInDB(BaseModel):
    id: int
    username: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class UserInResponse(BaseModel):
    username: str
    user_name: str
    user_type: str
    specialization: Optional[str] = None
    
class WorkRequest(BaseModel):
    specialization: str
    description: str
    price: float
    contact_info: str
    city_id: int

class WorkRequestInDB(BaseModel):
    id: int
    specialization: str
    description: str
    price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime
    executor_id: Optional[int] = None
    
class MachineryRequest(BaseModel):
    machinery_type: str
    description: str
    rental_price: float
    contact_info: str
    city_id: int
    
class MachineryRequestInDB(BaseModel):
    id: int
    machinery_type: str
    description: str
    rental_price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime
    
class ToolRequest(BaseModel):
    tool_name: str
    description: str
    rental_price: float
    contact_info: str
    city_id: int
    
class ToolRequestInDB(BaseModel):
    id: int
    tool_name: str
    description: str
    rental_price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime

class MaterialAd(BaseModel):
    material_type: str
    description: str
    price: float
    contact_info: str
    city_id: int
    
class MaterialAdInDB(BaseModel):
    id: int
    material_type: str
    description: str
    price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str
    
class UserCreate(BaseModel):
    username: str
    password: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class UserLogin(BaseModel): # <-- Добавлено
    username: str
    password: str

# Конфигурация
SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login") # <-- Добавлено

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

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось проверить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_type: str = payload.get("user_type")
        if username is None or user_type is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    if user is None:
        raise credentials_exception
    
    return UserInDB(**user._mapping)

@api_router.post("/login", response_model=Token)
async def login(form_data: UserLogin): # ✅ ИЗМЕНЕНО
    user_db = await users.fetch_one(users.select().where(users.c.username == form_data.username))
    if not user_db or not pwd_context.verify(form_data.password, user_db.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_db.username, "user_type": user_db.user_type},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.get("/profile/me", response_model=UserInResponse)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    return UserInResponse(**current_user.dict())

@api_router.post("/register", response_model=UserInResponse)
async def register_user(user: UserCreate):
    query = users.select().where(users.c.username == user.username)
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(status_code=400, detail="Имя пользователя уже зарегистрировано")

    password_hash = pwd_context.hash(user.password)

    query = users.insert().values(
        username=user.username,
        password_hash=password_hash,
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization
    )
    user_id = await database.execute(query)
    
    created_user = await database.fetch_one(users.select().where(users.c.id == user_id))

    return UserInResponse(**created_user._mapping)

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def get_work_requests(city_id: Optional[int] = None, specialization: Optional[str] = None):
    query = work_requests.select()
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    if specialization is not None:
        query = query.where(work_requests.c.specialization == specialization)
    
    requests = await database.fetch_all(query)
    return [WorkRequestInDB(**req._mapping) for req in requests]

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(work_request: WorkRequest, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только пользователи с типом 'ЗАКАЗЧИК' могут создавать заявки на работы.")
        
    query = work_requests.insert().values(
        specialization=work_request.specialization,
        description=work_request.description,
        price=work_request.price,
        contact_info=work_request.contact_info,
        city_id=work_request.city_id,
        user_id=current_user.id
    )
    
    request_id = await database.execute(query)
    
    created_request = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    return WorkRequestInDB(**created_request._mapping)
    
@api_router.post("/work-requests/{request_id}/take", response_model=WorkRequestInDB)
async def take_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    # Проверяем, является ли пользователь исполнителем или владельцем спецтехники
    if current_user.user_type not in ["ИСПОЛНИТЕЛЬ", "ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ"]:
        raise HTTPException(status_code=403, detail="Только исполнители могут принимать заявки.")

    # Получаем заявку, чтобы проверить, что она существует и не принята
    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)

    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    # Обновляем заявку, присваивая исполнителя
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    return WorkRequestInDB(**request._mapping)

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
        "Металл", "Дерево", "Цемент", "Кирпич", "Песок"
    ]
    return material_types
    
@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(machinery_request: MachineryRequest, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type not in ["ЗАКАЗЧИК", "ИСПОЛНИТЕЛЬ"]:
        raise HTTPException(status_code=403, detail="Только заказчики и исполнители могут создавать заявки на спецтехнику.")
        
    query = machinery_requests.insert().values(
        machinery_type=machinery_request.machinery_type,
        description=machinery_request.description,
        rental_price=machinery_request.rental_price,
        contact_info=machinery_request.contact_info,
        city_id=machinery_request.city_id,
        user_id=current_user.id
    )
    
    request_id = await database.execute(query)
    
    created_request = await database.fetch_one(machinery_requests.select().where(machinery_requests.c.id == request_id))
    return MachineryRequestInDB(**created_request._mapping)
    
@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(tool_request: ToolRequest, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type not in ["ЗАКАЗЧИК", "ИСПОЛНИТЕЛЬ"]:
        raise HTTPException(status_code=403, detail="Только заказчики и исполнители могут создавать заявки на инструменты.")
        
    query = tool_requests.insert().values(
        tool_name=tool_request.tool_name,
        description=tool_request.description,
        rental_price=tool_request.rental_price,
        contact_info=tool_request.contact_info,
        city_id=tool_request.city_id,
        user_id=current_user.id
    )
    
    request_id = await database.execute(query)
    
    created_request = await database.fetch_one(tool_requests.select().where(tool_requests.c.id == request_id))
    return ToolRequestInDB(**created_request._mapping)

@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(material_ad: MaterialAd, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ПОСТАВЩИК МАТЕРИАЛОВ":
        raise HTTPException(status_code=403, detail="Только поставщики могут создавать объявления о материалах.")
        
    query = material_ads.insert().values(
        material_type=material_ad.material_type,
        description=material_ad.description,
        price=material_ad.price,
        contact_info=material_ad.contact_info,
        city_id=material_ad.city_id,
        user_id=current_user.id
    )
    
    ad_id = await database.execute(query)
    
    created_ad = await database.fetch_one(material_ads.select().where(material_ads.c.id == ad_id))
    return MaterialAdInDB(**created_ad._mapping)

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def get_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id is not None:
        query = query.where(material_ads.c.city_id == city_id)
    
    ads = await database.fetch_all(query)
    return [MaterialAdInDB(**ad._mapping) for ad in ads]

@app.get("/")
def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)

app.include_router(api_router)