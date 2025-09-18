import json
import uvicorn
import databases
from jose import jwt, JWTError
from datetime import timedelta
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse

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

# Монтирование директории для статических файлов
app.mount("/static", StaticFiles(directory="static"), name="static")

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

class UserInDB(BaseModel):
    id: int
    username: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None
    is_premium: bool

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class WorkRequestCreate(BaseModel):
    description: str
    budget: float
    specialization: str
    contact_info: Optional[str] = None

class WorkRequestInDB(BaseModel):
    id: int
    description: str
    budget: float
    specialization: str
    contact_info: Optional[str] = None
    city_id: int
    user_id: int
    executor_id: Optional[int] = None
    is_premium: bool
    created_at: datetime

class MachineryRequestCreate(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str

class MachineryRequestInDB(BaseModel):
    id: int
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str

class MaterialAdInDB(BaseModel):
    id: int
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime

class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    count: Optional[int] = 1
    rental_period: Optional[str] = None
    contact_info: str

class ToolRequestInDB(BaseModel):
    id: int
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    count: Optional[int] = 1
    rental_period: Optional[str] = None
    contact_info: str
    city_id: int
    user_id: int
    created_at: datetime

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

async def get_user_by_username(username: str):
    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    return user

async def get_current_user(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    user = await get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return UserInDB(**user._mapping)

@api_router.post("/token", response_model=Token)
async def login_for_access_token(username: str = Depends(lambda x: x.get("username")), password: str = Depends(lambda x: x.get("password"))):
    user = await get_user_by_username(username)
    if not user or not verify_password(password, user._mapping["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": user._mapping["username"], "exp": datetime.utcnow() + access_token_expires}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": encoded_jwt, "token_type": "bearer"}

@api_router.post("/users/", response_model=UserInDB)
async def create_user(user: UserCreate):
    if await get_user_by_username(user.username):
        raise HTTPException(status_code=400, detail="Имя пользователя уже существует")
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization
    )
    user_id = await database.execute(query)
    return await get_user_by_username(user.username)

@api_router.get("/users/me", response_model=UserInDB)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    return current_user

@api_router.put("/users/update-specialization", response_model=UserInDB)
async def update_user_specialization(specialization: str, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только исполнители могут изменять специализацию.")
    query = users.update().where(users.c.id == current_user.id).values(specialization=specialization)
    await database.execute(query)
    updated_user = await get_user_by_username(current_user.username)
    return UserInDB(**updated_user._mapping)

@api_router.post("/subscribe")
async def activate_premium_subscription(current_user: UserInDB = Depends(get_current_user)):
    if current_user.is_premium:
        raise HTTPException(status_code=400, detail="У вас уже активна премиум-подписка.")
    query = users.update().where(users.c.id == current_user.id).values(is_premium=True)
    await database.execute(query)
    return {"message": "Премиум-подписка успешно активирована!"}

@api_router.get("/users/my-requests")
async def get_my_requests(current_user: UserInDB = Depends(get_current_user)):
    work_query = work_requests.select().where(work_requests.c.user_id == current_user.id)
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == current_user.id)
    tool_query = tool_requests.select().where(tool_requests.c.user_id == current_user.id)
    material_query = material_ads.select().where(material_ads.c.user_id == current_user.id)

    work_list = await database.fetch_all(work_query)
    machinery_list = await database.fetch_all(machinery_query)
    tool_list = await database.fetch_all(tool_query)
    material_list = await database.fetch_all(material_query)

    return {
        "work_requests": work_list,
        "machinery_requests": machinery_list,
        "tool_requests": tool_list,
        "material_ads": material_list
    }

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(request: WorkRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = work_requests.insert().values(
        description=request.description,
        budget=request.budget,
        specialization=request.specialization,
        contact_info=request.contact_info,
        city_id=current_user.city_id,
        user_id=current_user.id,
        is_premium=current_user.is_premium
    )
    request_id = await database.execute(query)
    return await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def get_work_requests(current_user: UserInDB = Depends(get_current_user)):
    query = work_requests.select().where(work_requests.c.city_id == current_user.city_id).order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.post("/work-requests/{request_id}/take", response_model=WorkRequestInDB)
async def take_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только исполнители могут принимать заявки.")

    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)

    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")
    
    # Проверяем, что заявка еще не была принята
    if request._mapping["executor_id"] is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    # Обновляем заявку, присваивая исполнителя
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    # Обновляем объект request
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
        "Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Каток", "Мини-погрузчик", "Манипулятор"
    ]
    return machinery_types

@api_router.get("/tools-list")
async def get_tools_list():
    tools = [
        "Сварочный аппарат", "Бензогенератор", "Шуруповерт", "Отбойный молоток",
        "Перфоратор", "Болгарка", "Лазерный уровень", "Виброплита",
        "Бетономешалка", "Миксер", "Степлер", "Пила"
    ]
    return tools

@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(request: MachineryRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        machinery_type=request.machinery_type,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=current_user.city_id,
        user_id=current_user.id
    )
    request_id = await database.execute(query)
    return await database.fetch_one(machinery_requests.select().where(machinery_requests.c.id == request_id))

@api_router.get("/machinery-requests", response_model=List[MachineryRequestInDB])
async def get_machinery_requests(current_user: UserInDB = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.city_id == current_user.city_id).order_by(machinery_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(request: ToolRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = tool_requests.insert().values(
        tool_name=request.tool_name,
        description=request.description,
        rental_price=request.rental_price,
        count=request.count,
        rental_period=request.rental_period,
        contact_info=request.contact_info,
        city_id=current_user.city_id,
        user_id=current_user.id
    )
    request_id = await database.execute(query)
    return await database.fetch_one(tool_requests.select().where(tool_requests.c.id == request_id))

@api_router.get("/tool-requests", response_model=List[ToolRequestInDB])
async def get_tool_requests(current_user: UserInDB = Depends(get_current_user)):
    query = tool_requests.select().where(tool_requests.c.city_id == current_user.city_id).order_by(tool_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(ad: MaterialAdCreate, current_user: UserInDB = Depends(get_current_user)):
    query = material_ads.insert().values(
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        contact_info=ad.contact_info,
        city_id=current_user.city_id,
        user_id=current_user.id
    )
    ad_id = await database.execute(query)
    return await database.fetch_one(material_ads.select().where(material_ads.c.id == ad_id))

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def get_material_ads(current_user: UserInDB = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.city_id == current_user.city_id).order_by(material_ads.c.created_at.desc())
    return await database.fetch_all(query)

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/static/index.html")

app.include_router(api_router)