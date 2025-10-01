import json
import uvicorn
import databases
import asyncpg
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, Request, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import exc, or_
from sqlalchemy.sql import select, func
import os
from dotenv import load_dotenv
from pathlib import Path

# --- Database setup ---
# Импорт объектов базы данных из database.py
from database import (
    metadata, engine, users, work_requests, machinery_requests, 
    tool_requests, material_ads, cities, database, chat_messages, 
    SPECIALIZATIONS, MACHINERY_TYPES, TOOL_LIST, MATERIAL_TYPES
)

load_dotenv()

# Настройки для токенов
SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 часа

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")

app = FastAPI(title="СМЗ.РФ API")
api_router = APIRouter(prefix="/api")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --- AUTH UTILS ---
def verify_password(plain_password, hashed_password):
    """Проверяет соответствие открытого пароля и хэша."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """Создает хэш пароля."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Генерирует JWT токен доступа."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Извлекает текущего пользователя из токена."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    query = users.select().where(users.c.id == int(user_id))
    user = await database.fetch_one(query)
    if user is None:
        raise credentials_exception
    return user

async def is_email_taken(email: str) -> bool:
    """Проверяет, существует ли пользователь с данным email в базе данных."""
    query = users.select().where(users.c.email == email)
    user = await database.fetch_one(query)
    return user is not None


@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# ----------------------------------------------------
# --- Schemas ---
# ----------------------------------------------------

class UserIn(BaseModel):
    email: EmailStr
    username: Optional[str] = None # Сделано опциональным
    password: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None
    city_id: int

class UserOut(BaseModel):
    id: int
    email: EmailStr
    username: Optional[str] = None
    user_type: str
    phone_number: Optional[str] = None
    specialization: Optional[str] = None
    is_premium: bool
    rating: Optional[float] = 0.0
    rating_count: int = 0

class Token(BaseModel):
    access_token: str
    token_type: str

class WorkRequestIn(BaseModel):
    name: str
    phone_number: str
    description: str
    specialization: str
    budget: float
    city_id: int
    address: Optional[str] = None
    visit_date: Optional[datetime] = None

class WorkRequestOut(BaseModel):
    id: int
    user_id: int
    executor_id: Optional[int]
    name: str
    description: str
    specialization: str
    budget: float
    phone_number: str
    city_id: int
    created_at: datetime
    is_taken: bool
    chat_enabled: bool
    is_completed: bool
    address: Optional[str]
    visit_date: Optional[datetime]
    is_premium: Optional[bool]
    customer_rating: Optional[float] = None
    
class WorkRequestUpdate(BaseModel):
    is_completed: Optional[bool] = None

class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: str
    rental_price: float
    contact_info: str
    city_id: int
    rental_date: Optional[date] = None
    min_hours: int = 4

class MachineryRequestOut(BaseModel):
    id: int
    user_id: int
    machinery_type: str
    description: Optional[str]
    rental_date: Optional[date]
    min_hours: Optional[int]
    rental_price: float
    contact_info: str
    city_id: int
    created_at: datetime
    is_premium: Optional[bool]

class ToolRequestIn(BaseModel):
    tool_name: str
    description: str
    rental_price: float
    tool_count: int = 1
    contact_info: str
    city_id: int
    rental_start: Optional[date] = None
    rental_end: Optional[date] = None
    has_delivery: bool = False
    delivery_address: Optional[str] = None

class ToolRequestOut(BaseModel):
    id: int
    user_id: int
    tool_name: str
    description: Optional[str]
    rental_price: float
    tool_count: int
    contact_info: str
    city_id: int
    rental_start: Optional[date]
    rental_end: Optional[date]
    created_at: datetime
    is_premium: Optional[bool]
    has_delivery: bool
    delivery_address: Optional[str]

class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

class MaterialAdOut(BaseModel):
    id: int
    user_id: int
    material_type: str
    description: Optional[str]
    price: float
    contact_info: str
    city_id: int
    created_at: datetime
    is_premium: Optional[bool]

class CityOut(BaseModel):
    id: int
    name: str
    region: Optional[str] = None

class ChatMessageIn(BaseModel):
    message: str

class ChatMessageOut(BaseModel):
    id: int
    request_id: int
    sender_id: int
    message: str
    created_at: datetime

class RatingIn(BaseModel):
    rating: int # От 1 до 5


# ----------------------------------------------------
# --- API Endpoints ---
# ----------------------------------------------------

# --- AUTH & USERS ---
@api_router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserIn):
    """Регистрация нового пользователя."""
    if await is_email_taken(user_in.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email уже зарегистрирован.")

    hashed_password = get_password_hash(user_in.password)
    
    # ИСПРАВЛЕНИЕ: Проверка user_type в нижнем регистре
    if user_in.user_type.lower() == "worker" and not user_in.specialization:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Для исполнителя необходимо указать специализацию.")

    # ИСПРАВЛЕНИЕ: Добавление проверки city_id
    city_check = await database.fetch_one(cities.select().where(cities.c.id == user_in.city_id))
    if not city_check:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный City ID.")

    query = users.insert().values(
        email=user_in.email,
        username=user_in.username,
        hashed_password=hashed_password,
        phone_number=user_in.phone_number,
        user_type=user_in.user_type.lower(),
        specialization=user_in.specialization,
        city_id=user_in.city_id
    )
    try:
        last_record_id = await database.execute(query)
        created_user_query = users.select().where(users.c.id == last_record_id)
        created_user = await database.fetch_one(created_user_query)
        return created_user
    except exc.IntegrityError as e:
        # Более детальная обработка ошибки, если email уже занят, хотя мы уже проверяли
        if "users_email_key" in str(e):
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email уже зарегистрирован.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ошибка целостности данных.")


@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Получение JWT токена доступа."""
    query = users.select().where(users.c.email == form_data.username)
    user = await database.fetch_one(query)

    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user["id"]), "user_type": user["user_type"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """Получение данных текущего пользователя."""
    return current_user


@api_router.patch("/users/me/specialization", response_model=UserOut)
async def update_user_specialization(
    specialization: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Обновление специализации пользователя."""
    if current_user["user_type"] != "worker":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для исполнителей.")
    
    if specialization not in SPECIALIZATIONS:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверная специализация.")

    query = users.update().where(users.c.id == current_user["id"]).values(specialization=specialization)
    await database.execute(query)
    
    # Получаем обновленные данные
    updated_user_query = users.select().where(users.c.id == current_user["id"])
    return await database.fetch_one(updated_user_query)


# --- CITY & LISTS ---
@api_router.get("/cities", response_model=List[CityOut])
async def get_cities():
    """Получение списка городов."""
    query = cities.select().order_by(cities.c.name)
    return await database.fetch_all(query)

@api_router.get("/specializations", response_model=List[str])
async def get_specializations():
    """Получение списка специализаций."""
    return SPECIALIZATIONS

@api_router.get("/machinery_types", response_model=List[str])
async def get_machinery_types():
    """Получение списка типов спецтехники."""
    return MACHINERY_TYPES

@api_router.get("/tools_list", response_model=List[str])
async def get_tools_list():
    """Получение списка инструментов."""
    return TOOL_LIST

@api_router.get("/material_types", response_model=List[str])
async def get_material_types():
    """Получение списка типов материалов."""
    return MATERIAL_TYPES


# --- WORK REQUESTS ---
@api_router.post("/work_requests", response_model=WorkRequestOut, status_code=status.HTTP_201_CREATED)
async def create_work_request(work_request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    """Создание новой заявки на работу."""
    if current_user["user_type"] != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только заказчики могут создавать заявки на работу.")

    query = work_requests.insert().values(
        user_id=current_user["id"],
        name=work_request.name,
        phone_number=work_request.phone_number,
        description=work_request.description,
        specialization=work_request.specialization,
        budget=work_request.budget,
        city_id=work_request.city_id,
        address=work_request.address,
        visit_date=work_request.visit_date,
        is_premium=current_user["is_premium"] # Премиум статус влияет на видимость
    )
    last_record_id = await database.execute(query)
    return await database.fetch_one(work_requests.select().where(work_requests.c.id == last_record_id))


@api_router.get("/work_requests/{city_id}", response_model=List[WorkRequestOut])
async def get_work_requests(city_id: int, specialization: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Получение всех невыполненных заявок на работу в определенном городе, отсортированных по премиум статусу."""
    
    # ИСПРАВЛЕНИЕ: Добавляем фильтр по is_completed=False и is_taken=False
    query = work_requests.select().where(
        (work_requests.c.city_id == city_id) & 
        (work_requests.c.is_completed == False) &
        (work_requests.c.is_taken == False)
    )

    if specialization:
        query = query.where(work_requests.c.specialization == specialization)

    # Заявки текущего пользователя не показываем, чтобы он сам их не брал.
    query = query.where(work_requests.c.user_id != current_user["id"])

    # Сортировка: Сначала премиум, потом по дате
    query = query.order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc())
    
    return await database.fetch_all(query)


@api_router.post("/work_requests/{request_id}/take", response_model=WorkRequestOut)
async def take_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    """Исполнитель берет заявку в работу. Активируется чат."""
    if current_user["user_type"] != "worker":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только исполнители могут брать заявки.")

    # 1. Проверяем, существует ли заявка и не взята ли она
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_data = await database.fetch_one(request_query)

    if not request_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена.")
    
    if request_data["is_taken"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заявка уже взята в работу.")

    if request_data["user_id"] == current_user["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя взять свою собственную заявку.")

    # 2. Обновляем заявку
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(
        executor_id=current_user["id"],
        is_taken=True,
        chat_enabled=True # Включаем чат после взятия
    )
    await database.execute(update_query)

    # 3. Получаем обновленную заявку
    updated_request_data = await database.fetch_one(request_query)
    return updated_request_data


@api_router.get("/work_requests/my", response_model=List[WorkRequestOut])
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    """Получение заявок, созданных пользователем (customer) или взятых им (worker)."""
    
    # ИСПРАВЛЕНИЕ: Добавление подзапроса для получения рейтинга заказчика
    
    # 1. Заявки, которые создал текущий пользователь (user_id = current_user.id)
    # 2. Заявки, которые взял в работу текущий пользователь (executor_id = current_user.id)
    query = work_requests.select().where(
        or_(
            work_requests.c.user_id == current_user["id"],
            work_requests.c.executor_id == current_user["id"]
        )
    ).order_by(work_requests.c.created_at.desc())
    
    # Выполняем основной запрос
    requests = await database.fetch_all(query)

    # Добавляем рейтинг заказчика к каждой заявке
    requests_with_rating = []
    for req in requests:
        # Для заказчика, его рейтинг - его собственный рейтинг
        if req["user_id"] == current_user["id"]:
            customer_rating = current_user["rating"]
        else:
            # Для исполнителя, нужно получить рейтинг заказчика
            customer_query = users.select(users.c.rating).where(users.c.id == req["user_id"])
            customer_rating_data = await database.fetch_one(customer_query)
            customer_rating = customer_rating_data["rating"] if customer_rating_data else 0.0
            
        requests_with_rating.append({**req, "customer_rating": customer_rating})

    return requests_with_rating


@api_router.patch("/work_requests/{request_id}", response_model=WorkRequestOut)
async def update_work_request_status(
    request_id: int, 
    update_data: WorkRequestUpdate, 
    current_user: dict = Depends(get_current_user)
):
    """Обновление статуса заявки (например, завершение)."""
    
    request_data = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))

    if not request_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена.")

    # Разрешаем завершить только заказчику или исполнителю, причастному к заявке
    if request_data["user_id"] != current_user["id"] and request_data["executor_id"] != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет прав на изменение этой заявки.")
        
    update_values = update_data.model_dump(exclude_unset=True)
    
    if update_values:
        query = work_requests.update().where(work_requests.c.id == request_id).values(**update_values)
        await database.execute(query)
    
    return await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))

# --- RATING ---
@api_router.post("/work_requests/{request_id}/rate", response_model=UserOut)
async def rate_executor(request_id: int, rating_in: RatingIn, current_user: dict = Depends(get_current_user)):
    """Оценка исполнителя заказчиком после завершения заявки."""
    
    if rating_in.rating < 1 or rating_in.rating > 5:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Рейтинг должен быть от 1 до 5.")

    request_data = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    
    if not request_data or request_data["user_id"] != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Вы не можете оценить эту заявку.")

    if not request_data["is_completed"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заявка не завершена.")

    executor_id = request_data["executor_id"]
    if not executor_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="У заявки нет исполнителя.")

    # Получаем данные исполнителя
    executor_query = users.select().where(users.c.id == executor_id)
    executor = await database.fetch_one(executor_query)
    
    # Обновляем рейтинг
    new_rating_count = executor["rating_count"] + 1
    new_total_rating = (executor["rating"] * executor["rating_count"]) + rating_in.rating
    new_rating = new_total_rating / new_rating_count

    update_query = users.update().where(users.c.id == executor_id).values(
        rating=new_rating,
        rating_count=new_rating_count
    )
    await database.execute(update_query)
    
    # Получаем обновленные данные исполнителя
    return await database.fetch_one(executor_query)


# --- CHATS ---
@api_router.get("/chats/my", response_model=List[dict])
async def get_my_chats(current_user: dict = Depends(get_current_user)):
    """Получение списка активных чатов пользователя."""
    
    # Заявки, где пользователь - заказчик ИЛИ исполнитель, и чат включен
    query = work_requests.select().where(
        or_(
            work_requests.c.user_id == current_user["id"],
            work_requests.c.executor_id == current_user["id"]
        ) & (work_requests.c.chat_enabled == True)
    ).order_by(work_requests.c.created_at.desc())
    
    requests_with_chat = await database.fetch_all(query)
    
    chat_list = []
    for req in requests_with_chat:
        # Определяем ID собеседника
        if req["user_id"] == current_user["id"] and req["executor_id"]:
            other_user_id = req["executor_id"]
            role = "Заказчик"
        elif req["executor_id"] == current_user["id"]:
            other_user_id = req["user_id"]
            role = "Исполнитель"
        else:
            continue # Пропускаем, если чат включен, но нет исполнителя (не должно быть, но для безопасности)

        other_user_query = users.select(users.c.email, users.c.username).where(users.c.id == other_user_id)
        other_user = await database.fetch_one(other_user_query)
        
        chat_list.append({
            "request_id": req["id"],
            "request_description": req["description"][:50] + "...",
            "other_user_email": other_user["email"] if other_user else "Unknown",
            "other_user_username": other_user["username"] if other_user else "Неизвестно",
            "your_role": role,
            "is_completed": req["is_completed"],
            "executor_id": req["executor_id"] # Нужен для определения, кого оценивать
        })
        
    return chat_list


@api_router.get("/chats/{request_id}/messages", response_model=List[ChatMessageOut])
async def get_chat_messages(request_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех сообщений для конкретного чата."""
    
    # Проверка прав доступа: пользователь должен быть заказчиком или исполнителем заявки
    request_data = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    
    if not request_data or (request_data["user_id"] != current_user["id"] and request_data["executor_id"] != current_user["id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа к этому чату.")
        
    if not request_data["chat_enabled"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Чат по этой заявке не активирован.")

    query = chat_messages.select().where(chat_messages.c.request_id == request_id).order_by(chat_messages.c.created_at.asc())
    return await database.fetch_all(query)


@api_router.post("/chats/{request_id}/send", response_model=ChatMessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(request_id: int, message_in: ChatMessageIn, current_user: dict = Depends(get_current_user)):
    """Отправка нового сообщения в чат."""
    
    # Проверка прав доступа
    request_data = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    
    if not request_data or (request_data["user_id"] != current_user["id"] and request_data["executor_id"] != current_user["id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа к этому чату.")
        
    if not request_data["chat_enabled"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Чат по этой заявке не активирован.")
        
    query = chat_messages.insert().values(
        request_id=request_id,
        sender_id=current_user["id"],
        message=message_in.message
    )
    last_record_id = await database.execute(query)
    return await database.fetch_one(chat_messages.select().where(chat_messages.c.id == last_record_id))

# --- MACHINERY REQUESTS ---
# (Аналогичные роуты для спецтехники, инструментов и материалов)
@api_router.post("/machinery_requests", response_model=MachineryRequestOut, status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request_in: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        user_id=current_user["id"],
        **request_in.model_dump(),
        is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    return await database.fetch_one(machinery_requests.select().where(machinery_requests.c.id == last_record_id))

@api_router.get("/machinery_requests/{city_id}", response_model=List[MachineryRequestOut])
async def get_machinery_requests(city_id: int, current_user: dict = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.city_id == city_id).order_by(machinery_requests.c.is_premium.desc(), machinery_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.get("/machinery_requests/my", response_model=List[MachineryRequestOut])
async def get_my_machinery_requests(current_user: dict = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.user_id == current_user["id"]).order_by(machinery_requests.c.created_at.desc())
    return await database.fetch_all(query)


# --- TOOL REQUESTS ---
@api_router.post("/tool_requests", response_model=ToolRequestOut, status_code=status.HTTP_201_CREATED)
async def create_tool_request(request_in: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    query = tool_requests.insert().values(
        user_id=current_user["id"],
        **request_in.model_dump(),
        is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    return await database.fetch_one(tool_requests.select().where(tool_requests.c.id == last_record_id))

@api_router.get("/tool_requests/{city_id}", response_model=List[ToolRequestOut])
async def get_tool_requests(city_id: int, current_user: dict = Depends(get_current_user)):
    query = tool_requests.select().where(tool_requests.c.city_id == city_id).order_by(tool_requests.c.is_premium.desc(), tool_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.get("/tool_requests/my", response_model=List[ToolRequestOut])
async def get_my_tool_requests(current_user: dict = Depends(get_current_user)):
    query = tool_requests.select().where(tool_requests.c.user_id == current_user["id"]).order_by(tool_requests.c.created_at.desc())
    return await database.fetch_all(query)


# --- MATERIAL ADS ---
@api_router.post("/material_ads", response_model=MaterialAdOut, status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad_in: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    query = material_ads.insert().values(
        user_id=current_user["id"],
        **ad_in.model_dump(),
        is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    return await database.fetch_one(material_ads.select().where(material_ads.c.id == last_record_id))


@api_router.get("/material_ads/{city_id}", response_model=List[MaterialAdOut])
async def get_material_ads(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех объявлений о материалах в определенном городе."""
    query = material_ads.select().where(material_ads.c.city_id == city_id).order_by(material_ads.c.is_premium.desc(), material_ads.c.created_at.desc())
    return await database.fetch_all(query)


@api_router.get("/material_ads/my", response_model=List[MaterialAdOut])
async def get_my_material_ads(current_user: dict = Depends(get_current_user)):
    """Получение объявлений о материалах, созданных текущим пользователем."""
    query = material_ads.select().where(material_ads.c.user_id == current_user["id"]).order_by(material_ads.c.created_at.desc())
    return await database.fetch_all(query)


# ----------------------------------------------------
# --- Static Files Mounting ---
# ----------------------------------------------------
app.include_router(api_router)

static_path = Path(__file__).parent / "static" # Эта строка у вас есть
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    # ИСПРАВЛЕНИЕ: Используем Path для создания правильного пути
    return FileResponse(static_path / "index.html") 

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)