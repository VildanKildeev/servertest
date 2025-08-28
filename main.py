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
from fastapi.security import OAuth2PasswordBearer # <-- Добавлен импорт

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

# Pydantic models (все классы-модели должны быть здесь)
class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
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

class WorkRequest(BaseModel):
    title: str
    description: Optional[str] = None
    specialization: str
    city_id: int
    user_id: Optional[int] = None
    created_at: Optional[datetime] = None
    executor_id: Optional[int] = None

class WorkRequestInDB(WorkRequest):
    id: int

class MachineryRequest(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class MachineryRequestInDB(MachineryRequest):
    id: int

class ToolRequest(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class ToolRequestInDB(ToolRequest):
    id: int

class MaterialAd(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

class MaterialAdInDB(MaterialAd):
    id: int

# Определяем oauth2_scheme здесь, ДО функции get_current_user
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# Теперь get_current_user может использовать oauth2_scheme
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

@api_router.post("/token", response_model=Token)
async def login_for_access_token(user_data: dict):
    query = users.select().where(users.c.username == user_data["username"])
    user = await database.fetch_one(query)
    if not user or not verify_password(user_data["password"], user["password_hash"]):
        raise HTTPException(status_code=400, detail="Неверное имя пользователя или пароль.")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    user_in_db = UserInDB(**user._mapping)
    access_token = create_access_token(
        data={
            "sub": user_in_db.username,
            "user_name": user_in_db.user_name,
            "user_type": user_in_db.user_type,
            "city_id": user_in_db.city_id,
            "specialization": user_in_db.specialization
        },
        expires_delta=access_token_expires,
    )
    return {
        "access_token": access_token, 
        "token_type": "bearer", 
        "username": user_in_db.username,
        "user_name": user_in_db.user_name,
        "user_type": user_in_db.user_type,
        "city_id": user_in_db.city_id,
        "specialization": user_in_db.specialization
    }

@api_router.post("/register")
async def register_user(user_data: dict):
    query = users.select().where(users.c.username == user_data["username"])
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(status_code=400, detail="Это имя пользователя уже занято.")

    hashed_password = get_password_hash(user_data["password"])
    query = users.insert().values(
        username=user_data["username"],
        password_hash=hashed_password,
        user_name=user_data["user_name"],
        user_type=user_data["user_type"],
        city_id=user_data["city_id"],
        specialization=user_data.get("specialization")
    )
    await database.execute(query)
    return {"message": "Пользователь успешно зарегистрирован."}

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def get_work_requests(city_id: Optional[int] = None):
    query = work_requests.select()
    if city_id:
        query = query.where(work_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [WorkRequestInDB(**req._mapping) for req in requests]

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(request: WorkRequest, current_user: UserInDB = Depends(get_current_user)):
    query = work_requests.insert().values(
        title=request.title,
        description=request.description,
        specialization=request.specialization,
        city_id=request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return WorkRequestInDB(id=last_record_id, **request.dict(), user_id=current_user.id)

@api_router.post("/work-requests/{request_id}/take", response_model=WorkRequestInDB)
async def take_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    # Проверяем, является ли пользователь "ИСПОЛНИТЕЛЕМ"
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только 'ИСПОЛНИТЕЛИ' могут принимать заявки.")

    # Проверяем, существует ли заявка и не была ли она уже принята
    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)
    if request is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")
    
    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    # Обновляем заявку, присваивая исполнителя
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    # Получаем обновленную заявку для возврата
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

@api_router.get("/machinery-requests", response_model=List[MachineryRequestInDB])
async def get_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select()
    if city_id:
        query = query.where(machinery_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [MachineryRequestInDB(**req._mapping) for req in requests]

@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(request: MachineryRequest, current_user: UserInDB = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        machinery_type=request.machinery_type,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return MachineryRequestInDB(id=last_record_id, **request.dict(), user_id=current_user.id)

@api_router.get("/tool-requests", response_model=List[ToolRequestInDB])
async def get_tool_requests(city_id: Optional[int] = None):
    query = tool_requests.select()
    if city_id:
        query = query.where(tool_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [ToolRequestInDB(**req._mapping) for req in requests]

@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(request: ToolRequest, current_user: UserInDB = Depends(get_current_user)):
    query = tool_requests.insert().values(
        tool_name=request.tool_name,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return ToolRequestInDB(id=last_record_id, **request.dict(), user_id=current_user.id)

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def get_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id:
        query = query.where(material_ads.c.city_id == city_id)
    ads = await database.fetch_all(query)
    return [MaterialAdInDB(**ad._mapping) for ad in ads]

@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(ad: MaterialAd, current_user: UserInDB = Depends(get_current_user)):
    query = material_ads.insert().values(
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        contact_info=ad.contact_info,
        city_id=ad.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return MaterialAdInDB(id=last_record_id, **ad.dict(), user_id=current_user.id)


app.include_router(api_router)

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)