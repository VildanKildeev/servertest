import json
import uvicorn
import databases
import sqlalchemy
import os
from dotenv import load_dotenv
from jose import jwt, JWTError
from datetime import timedelta
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles # <-- Исправлено: Импорт для обслуживания статических файлов
from fastapi.responses import FileResponse # <-- Исправлено: Импорт для возврата файла
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# Загружаем переменные окружения из файла .env
load_dotenv()

# Импортируем все из вашего файла database.py
try:
    from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL
    database = databases.Database(DATABASE_URL)
except ImportError:
    raise ImportError("Не найден файл database.py. Убедитесь, что он находится в корневой директории вашего проекта.")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Исправлено: Определяем OAuth2-схему для получения токена
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

# Создаем экземпляр FastAPI
app = FastAPI(title="СМЗ.РФ API")

# Создаем роутер для API
api_router = APIRouter(prefix="/api")

# Добавляем middleware для CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Обработчики событий для подключения к базе данных
@app.on_event("startup")
async def startup():
    metadata.create_all(engine)
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# =========================================================================
# Правильная настройка для обслуживания статических файлов
# =========================================================================

# Монтируем директорию "static" для обслуживания статических файлов (CSS, JS, и т.д.)
# Это позволит вашим HTML-файлам ссылаться на `/static/style.css` и т.п.
app.mount("/static", StaticFiles(directory="static"), name="static")

# Определяем корневой маршрут, который будет возвращать index.html
# Мы используем FileResponse, так как это наиболее прямой и эффективный способ.
@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")

# =========================================================================
# ВАШИ API-ЭНДПОЙНТЫ И Pydantic МОДЕЛИ
# =========================================================================

# Pydantic модели
class UserIn(BaseModel):
    username: str
    password: str
    user_name: Optional[str] = None
    user_type: Optional[str] = None
    city_id: Optional[int] = None
    specialization: Optional[str] = None

class UserOut(BaseModel):
    id: int
    username: str
    user_name: Optional[str]
    user_type: Optional[str]
    city_id: Optional[int]
    specialization: Optional[str]

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class WorkRequestIn(BaseModel):
    title: str
    description: Optional[str] = None
    specialization: str
    budget: Optional[float] = None
    city_id: int

class WorkRequestInDB(WorkRequestIn):
    id: int
    user_id: int
    created_at: datetime
    executor_id: Optional[int]

class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class MachineryRequestInDB(MachineryRequestIn):
    id: int
    user_id: int
    created_at: datetime

class ToolRequestIn(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class ToolRequestInDB(ToolRequestIn):
    id: int
    user_id: int
    created_at: datetime

class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

class MaterialAdInDB(MaterialAdIn):
    id: int
    user_id: int
    created_at: datetime

class TakeOrder(BaseModel):
    executor_id: int

class User(BaseModel):
    id: int
    username: str
    user_type: str
    city_id: int

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

async def authenticate_user(username: str, password: str):
    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    if not user or not verify_password(password, user.password_hash):
        return False
    return user

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
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    query = users.select().where(users.c.username == token_data.username)
    user = await database.fetch_one(query)
    if user is None:
        raise credentials_exception
    return UserIn(**user._mapping)

@api_router.post("/register", response_model=Token)
async def register(user: UserIn):
    # Проверяем, существует ли уже пользователь
    query = users.select().where(users.c.username == user.username)
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(status_code=400, detail="Имя пользователя уже зарегистрировано")

    # Хэшируем пароль
    hashed_password = get_password_hash(user.password)

    # Вставляем нового пользователя в БД
    insert_query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization
    )
    last_record_id = await database.execute(insert_query)
    
    # Создаем токен для нового пользователя
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.post("/token")
async def login_for_access_token(user: UserIn):
    user_db = await authenticate_user(user.username, user.password)
    if not user_db:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неправильное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.get("/profile", response_model=UserIn)
async def get_profile(current_user: UserIn = Depends(get_current_user)):
    return current_user

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(work_request: WorkRequestIn, current_user: UserIn = Depends(get_current_user)):
    insert_query = work_requests.insert().values(
        title=work_request.title,
        description=work_request.description,
        specialization=work_request.specialization,
        budget=work_request.budget,
        city_id=work_request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(insert_query)
    return {**work_request.dict(), "id": last_record_id, "user_id": current_user.id, "created_at": datetime.now(), "executor_id": None}

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def get_work_requests(current_user: UserIn = Depends(get_current_user)):
    query = work_requests.select().where(work_requests.c.city_id == current_user.city_id)
    requests = await database.fetch_all(query)
    return [WorkRequestInDB(**req._mapping) for req in requests]

@api_router.post("/work-requests/{request_id}/take")
async def take_work_request(request_id: int, current_user: UserIn = Depends(get_current_user)):
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

app.include_router(api_router)

# Запуск Uvicorn-сервера
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))