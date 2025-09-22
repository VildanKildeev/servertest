import json
import uvicorn
import databases
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy import exc
from sqlalchemy.orm import relationship
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

import os
from dotenv import load_dotenv

# --- Database setup ---
# Импортируем все таблицы и метаданные из файла database.py
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities, database

load_dotenv()

# Настройки для токенов
SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

app = FastAPI(title="СМЗ.РФ API")
api_router = APIRouter(prefix="/api")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# Создаем таблицы в базе данных при запуске, если они еще не существуют
@app.on_event("startup")
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

# --- Password hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# --- JWT Token creation ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- Pydantic models ---
class UserInDB(BaseModel):
    id: int
    username: str
    user_name: str
    email: Optional[str] = None
    user_type: str
    specialization: Optional[str] = None
    is_premium: bool

class UserCreate(BaseModel):
    username: str
    password: str
    user_name: str
    email: Optional[str] = None
    user_type: str

class User(BaseModel):
    username: str
    user_name: str
    email: Optional[str] = None
    user_type: str
    specialization: Optional[str] = None
    is_premium: bool

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class WorkRequestCreate(BaseModel):
    description: str
    specialization: str
    budget: float
    contact_info: str
    city_id: int

class WorkRequest(WorkRequestCreate):
    id: int
    user_id: int
    executor_id: Optional[int] = None
    created_at: datetime
    is_premium: bool
    status: str

class MachineryRequestCreate(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class MachineryRequest(MachineryRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    is_premium: bool

class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    count: Optional[int] = 1
    rental_start_date: Optional[date] = None
    rental_end_date: Optional[date] = None
    contact_info: str
    has_delivery: Optional[bool] = False
    delivery_address: Optional[str] = None
    city_id: int

class ToolRequest(ToolRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    is_premium: bool

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

class MaterialAd(MaterialAdCreate):
    id: int
    user_id: int
    created_at: datetime
    is_premium: bool

class City(BaseModel):
    id: int
    name: str

# --- Authentication and dependency functions ---
async def get_user(username: str):
    query = users.select().where(users.c.username == username)
    return await database.fetch_one(query)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token_data = TokenData(username=username)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = await get_user(token_data.username)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user

# --- API Endpoints ---
@api_router.post("/users/", response_model=User, status_code=201)
async def create_user(user: UserCreate):
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        username=user.username,
        hashed_password=hashed_password,
        user_name=user.user_name,
        email=user.email,
        user_type=user.user_type,
        is_premium=False
    )
    try:
        await database.execute(query)
        created_user = await get_user(user.username)
        return User(**created_user)
    except exc.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already registered")

@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await get_user(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.get("/users/me", response_model=UserInDB)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    return current_user

@api_router.put("/users/update-specialization", response_model=UserInDB)
async def update_user_specialization(specialization: str, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Only 'ИСПОЛНИТЕЛЬ' can have a specialization.")
    
    query = users.update().where(users.c.id == current_user.id).values(specialization=specialization)
    await database.execute(query)
    
    updated_user = await get_user(current_user.username)
    return updated_user

@api_router.post("/subscribe")
async def subscribe_user(current_user: UserInDB = Depends(get_current_user)):
    if current_user.is_premium:
        raise HTTPException(status_code=400, detail="User already has a premium subscription.")

    query = users.update().where(users.c.id == current_user.id).values(is_premium=True)
    await database.execute(query)
    return {"message": "Subscription activated successfully."}

# Endpoints for work requests
@api_router.post("/work_requests", response_model=WorkRequest)
async def create_work_request(request: WorkRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Only 'ЗАКАЗЧИК' can create work requests.")
    
    query = work_requests.insert().values(
        user_id=current_user.id,
        description=request.description,
        specialization=request.specialization,
        budget=request.budget,
        contact_info=request.contact_info,
        city_id=request.city_id,
        is_premium=current_user.is_premium
    )
    request_id = await database.execute(query)
    created_request = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    return created_request

@api_router.get("/work_requests", response_model=List[WorkRequest])
async def get_work_requests(city_id: int, current_user: UserInDB = Depends(get_current_user)):
    query = work_requests.select().where(work_requests.c.city_id == city_id).order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc())
    if current_user.user_type == "ИСПОЛНИТЕЛЬ":
        query = query.where(work_requests.c.executor_id == None)
    
    return await database.fetch_all(query)

@api_router.put("/work_requests/{request_id}/take", response_model=WorkRequest)
async def take_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Only 'ИСПОЛНИТЕЛЬ' can take work requests.")
    
    existing_request = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not existing_request:
        raise HTTPException(status_code=404, detail="Work request not found.")
    
    if existing_request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Work request has already been taken.")

    query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(query)
    
    updated_request = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    return updated_request

# Endpoints for machinery requests
@api_router.post("/machinery_requests", response_model=MachineryRequest)
async def create_machinery_request(request: MachineryRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        user_id=current_user.id,
        machinery_type=request.machinery_type,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id,
        is_premium=current_user.is_premium
    )
    request_id = await database.execute(query)
    created_request = await database.fetch_one(machinery_requests.select().where(machinery_requests.c.id == request_id))
    return created_request

@api_router.get("/machinery_requests", response_model=List[MachineryRequest])
async def get_machinery_requests(city_id: int, current_user: UserInDB = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.city_id == city_id).order_by(machinery_requests.c.is_premium.desc(), machinery_requests.c.created_at.desc())
    return await database.fetch_all(query)

# Endpoints for tool requests
@api_router.post("/tool_requests", response_model=ToolRequest)
async def create_tool_request(request: ToolRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = tool_requests.insert().values(
        user_id=current_user.id,
        tool_name=request.tool_name,
        description=request.description,
        rental_price=request.rental_price,
        count=request.count,
        rental_start_date=request.rental_start_date,
        rental_end_date=request.rental_end_date,
        contact_info=request.contact_info,
        has_delivery=request.has_delivery,
        delivery_address=request.delivery_address,
        city_id=request.city_id,
        is_premium=current_user.is_premium
    )
    request_id = await database.execute(query)
    created_request = await database.fetch_one(tool_requests.select().where(tool_requests.c.id == request_id))
    return created_request

@api_router.get("/tool_requests", response_model=List[ToolRequest])
async def get_tool_requests(city_id: int, current_user: UserInDB = Depends(get_current_user)):
    query = tool_requests.select().where(tool_requests.c.city_id == city_id).order_by(tool_requests.c.is_premium.desc(), tool_requests.c.created_at.desc())
    return await database.fetch_all(query)

# Endpoints for material ads
@api_router.post("/material_ads", response_model=MaterialAd)
async def create_material_ad(ad: MaterialAdCreate, current_user: UserInDB = Depends(get_current_user)):
    query = material_ads.insert().values(
        user_id=current_user.id,
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        contact_info=ad.contact_info,
        city_id=ad.city_id,
        is_premium=current_user.is_premium
    )
    ad_id = await database.execute(query)
    created_ad = await database.fetch_one(material_ads.select().where(material_ads.c.id == ad_id))
    return created_ad

@api_router.get("/material_ads", response_model=List[MaterialAd])
async def get_material_ads(city_id: int, current_user: UserInDB = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.city_id == city_id).order_by(material_ads.c.is_premium.desc(), material_ads.c.created_at.desc())
    return await database.fetch_all(query)

# Endpoints for user's own requests
@api_router.get("/users/me/requests", response_model=dict)
async def get_my_requests(city_id: int, current_user: UserInDB = Depends(get_current_user)):
    work_query = work_requests.select().where(work_requests.c.user_id == current_user.id, work_requests.c.city_id == city_id).order_by(work_requests.c.created_at.desc())
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == current_user.id, machinery_requests.c.city_id == city_id).order_by(machinery_requests.c.created_at.desc())
    tool_query = tool_requests.select().where(tool_requests.c.user_id == current_user.id, tool_requests.c.city_id == city_id).order_by(tool_requests.c.created_at.desc())
    material_query = material_ads.select().where(material_ads.c.user_id == current_user.id, material_ads.c.city_id == city_id).order_by(material_ads.c.created_at.desc())

    my_work_requests = await database.fetch_all(work_query)
    my_machinery_requests = await database.fetch_all(machinery_query)
    my_tool_requests = await database.fetch_all(tool_query)
    my_material_ads = await database.fetch_all(material_query)

    return {
        "work_requests": my_work_requests,
        "machinery_requests": my_machinery_requests,
        "tool_requests": my_tool_requests,
        "material_ads": my_material_ads
    }

# Endpoints for lists
@api_router.get("/cities", response_model=List[City])
async def get_cities():
    cities_list = ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань"]
    # Проверяем, есть ли города в базе, если нет - добавляем
    query = cities.select()
    existing_cities = await database.fetch_all(query)
    if not existing_cities:
        for city_name in cities_list:
            insert_query = cities.insert().values(name=city_name)
            await database.execute(insert_query)
        existing_cities = await database.fetch_all(query)
    
    return [City(id=c['id'], name=c['name']) for c in existing_cities]


@api_router.get("/specializations")
async def get_specializations():
    return [
        "Мастер на час", "Электрик", "Сантехник", "Отделочные работы",
        "Мебельщик", "Грузоперевозки", "Маляр-штукатур", "Кровельные работы",
        "Установка дверей", "Окна", "Клининг", "Сборка мебели",
        "Ремонт бытовой техники", "Ремонт компьютеров", "Мастер по вентиляции и кондиционированию",
        "Утепление", "Фасадные работы"
    ]

@api_router.get("/machinery-types")
async def get_machinery_types():
    return ["Экскаватор", "Погрузчик", "Манипулятор", "Автокран", "Самосвал", "Каток", "Автовышка"]

@api_router.get("/tools-list")
async def get_tools_list():
    return [
        "Бетономешалка", "Отбойный молоток", "Перфоратор", "Шуруповерт", "Болгарка",
        "Торцовочная пила", "Сварочный аппарат", "Паяльник для труб", "Виброплита",
        "Леса строительные", "Виброрейка", "Затирочная машина", "Генератор", "Компрессор",
        "Мотобур", "Мотопомпа", "Дренажный насос", "Плиткорез", "Краскопульс", "Фен строительный",
        "Промышленный пылесос", "Тепловая пушка", "Лазерный уровень", "Строительный степлер",
        "Лестница", "Вышка-тура", "Ручной инструмент", "Ручная тележка", "Домкрат",
        "Трубогиб", "Электрорубанок", "Пылесос"
    ]

app.include_router(api_router)

# Serve static files and HTML
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)