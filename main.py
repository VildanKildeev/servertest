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

# Pydantic models (Schemas)
class UserInDB(BaseModel):
    id: int
    username: str
    user_name: Optional[str] = None
    user_type: Optional[str] = None
    city_id: Optional[int] = None
    specialization: Optional[str] = None

class UserOut(BaseModel):
    user_name: str
    user_type: str
    city_id: Optional[int] = None
    specialization: Optional[str] = None
    
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class User(BaseModel):
    username: str
    password: str
    user_name: Optional[str] = None
    user_type: str
    city_id: Optional[int] = None
    specialization: Optional[str] = None

class WorkRequestCreate(BaseModel):
    work_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

# ✅ ДОБАВЛЕНО: Pydantic модель для запроса на инструменты
class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class MachineryRequestCreate(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

# ✅ ДОБАВЛЕНО: Pydantic модель для запросов из БД
class WorkRequestInDB(WorkRequestCreate):
    id: int
    user_id: int
    executor_id: Optional[int] = None
    created_at: datetime
    
# ✅ ДОБАВЛЕНО: Pydantic модель для запросов из БД
class ToolRequestInDB(ToolRequestCreate):
    id: int
    user_id: int
    created_at: datetime

class MachineryRequestInDB(MachineryRequestCreate):
    id: int
    user_id: int
    created_at: datetime

class MaterialAdInDB(MaterialAdCreate):
    id: int
    user_id: int
    created_at: datetime

# Auth and User
def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

async def get_user(username: str):
    query = users.select().where(users.c.username == username)
    user_record = await database.fetch_one(query)
    if user_record:
        return UserInDB(**user_record._mapping)
    return None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
        token_data = TokenData(username=username)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
    user = await get_user(username=token_data.username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found", headers={"WWW-Authenticate": "Bearer"})
    return user

@api_router.post("/register", response_model=UserOut)
async def register_user(user: User):
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization
    )
    try:
        user_id = await database.execute(query)
        new_user = await get_user(user.username)
        return UserOut(user_name=new_user.user_name, user_type=new_user.user_type, city_id=new_user.city_id, specialization=new_user.specialization)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@api_router.post("/token", response_model=Token)
async def login_for_access_token(user: User):
    user_in_db = await get_user(user.username)
    if not user_in_db or not verify_password(user.password, user_in_db.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_in_db.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.get("/me", response_model=UserOut)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    return UserOut(user_name=current_user.user_name, user_type=current_user.user_type, city_id=current_user.city_id, specialization=current_user.specialization)

# Work Requests
@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(request: WorkRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = work_requests.insert().values(
        user_id=current_user.id,
        work_type=request.work_type,
        description=request.description,
        price=request.price,
        contact_info=request.contact_info,
        city_id=request.city_id
    )
    last_record_id = await database.execute(query)
    # Используем fetch_one, чтобы получить полную запись, включая created_at
    created_request = await database.fetch_one(work_requests.select().where(work_requests.c.id == last_record_id))
    return WorkRequestInDB(**created_request._mapping)

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def get_work_requests(city_id: Optional[int] = None):
    query = work_requests.select().where(work_requests.c.executor_id == None).order_by(work_requests.c.created_at.desc())
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [WorkRequestInDB(**req._mapping) for req in requests]

@api_router.post("/work-requests/{request_id}/take", response_model=WorkRequestInDB)
async def take_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    # Проверяем, существует ли заявка
    select_query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(select_query)
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")
    
    # Проверяем, не принята ли она уже
    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    # Обновляем заявку, присваивая исполнителя
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    # Получаем обновленную запись для возврата
    updated_request = await database.fetch_one(select_query)
    return WorkRequestInDB(**updated_request._mapping)


# Machinery Requests
@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(request: MachineryRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        user_id=current_user.id,
        machinery_type=request.machinery_type,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id
    )
    last_record_id = await database.execute(query)
    created_request = await database.fetch_one(machinery_requests.select().where(machinery_requests.c.id == last_record_id))
    return MachineryRequestInDB(**created_request._mapping)

@api_router.get("/machinery-requests", response_model=List[MachineryRequestInDB])
async def get_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select().order_by(machinery_requests.c.created_at.desc())
    if city_id is not None:
        query = query.where(machinery_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [MachineryRequestInDB(**req._mapping) for req in requests]


# ✅ ДОБАВЛЕНО: Эндпоинт для запросов на инструменты
@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(request: ToolRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = tool_requests.insert().values(
        user_id=current_user.id,
        tool_name=request.tool_name,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id
    )
    last_record_id = await database.execute(query)
    created_request = await database.fetch_one(tool_requests.select().where(tool_requests.c.id == last_record_id))
    return ToolRequestInDB(**created_request._mapping)

# ✅ ДОБАВЛЕНО: Эндпоинт для получения списка запросов на инструменты
@api_router.get("/tool-requests", response_model=List[ToolRequestInDB])
async def get_tool_requests(city_id: Optional[int] = None):
    query = tool_requests.select().order_by(tool_requests.c.created_at.desc())
    if city_id is not None:
        query = query.where(tool_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [ToolRequestInDB(**req._mapping) for req in requests]


# Material Ads
@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(ad: MaterialAdCreate, current_user: UserInDB = Depends(get_current_user)):
    query = material_ads.insert().values(
        user_id=current_user.id,
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        contact_info=ad.contact_info,
        city_id=ad.city_id
    )
    last_record_id = await database.execute(query)
    created_ad = await database.fetch_one(material_ads.select().where(material_ads.c.id == last_record_id))
    return MaterialAdInDB(**created_ad._mapping)

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def get_material_ads(city_id: Optional[int] = None):
    query = material_ads.select().order_by(material_ads.c.created_at.desc())
    if city_id is not None:
        query = query.where(material_ads.c.city_id == city_id)
    ads = await database.fetch_all(query)
    return [MaterialAdInDB(**ad._mapping) for ad in ads]

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
        "Кирпич", "Бетон", "Дерево", "Металл", "Сыпучие материалы", "Отделочные материалы"
    ]
    return material_types

app.include_router(api_router)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_app():
    return HTMLResponse(content=open("static/index.html", encoding="utf-8").read())