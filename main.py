import json
import uvicorn
import databases
import asyncpg
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, File, UploadFile, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import exc
from sqlalchemy.orm import relationship
import os
from dotenv import load_dotenv
from pathlib import Path


# --- Database setup ---
# Импорт объектов базы данных из database.py
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities, database, chat_messages

load_dotenv()


# Настройки для токенов
SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

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
        expire = datetime.utcnow() + timedelta(minutes=15)
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


# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ПРОВЕРКИ EMAIL
async def is_email_taken(email: str) -> bool:
    """Проверяет, существует ли пользователь с данным email в базе данных."""
    query = users.select().where(users.c.email == email)
    user = await database.fetch_one(query)
    return user is not None


@app.on_event("startup")
async def startup():
    print("Connecting to the database...")
    await database.connect()


@app.on_event("shutdown")
async def shutdown():
    print("Disconnecting from the database...")
    await database.disconnect()


# ----------------------------------------------------
# --- Schemas ---
# ----------------------------------------------------

class UserIn(BaseModel):
    """Схема для регистрации нового пользователя."""
    email: EmailStr
    password: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None
    city_id: int

class UserOut(BaseModel):
    id: int
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    is_active: Optional[bool] = True
    created_at: datetime
    city_id: Optional[int] = None
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False
    user_type: str
    
    # ИСПРАВЛЕНИЕ ДЛЯ ТЕКУЩЕЙ ОШИБКИ ('rating'):
    rating: Optional[float] = Field(None, description="Рейтинг пользователя", ge=0.0, le=5.0)
    
    # ИСПРАВЛЕНИЕ ДЛЯ ПРЕДЫДУЩЕЙ ОШИБКИ ('rating_count'):
    rating_count: Optional[int] = Field(None, description="Количество оценок", ge=0)
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    """Схема для токена доступа."""
    access_token: str
    token_type: str


# --- WORK REQUESTS SCHEMAS ---
class WorkRequestIn(BaseModel):
    """Схема для создания заявки на работу."""
    name: str
    phone_number: str
    description: str
    specialization: str
    budget: float
    city_id: int
    address: Optional[str] = None
    visit_date: Optional[datetime] = None

class WorkRequestOut(BaseModel):
    """Схема для выдачи данных заявки на работу."""
    id: int
    user_id: int
    executor_id: Optional[int]
    name: str
    description: str # ИСПРАВЛЕНИЕ: Убрано Optional[], чтобы соответствовать nullable=False в базе данных.
    specialization: str
    budget: float
    phone_number: str
    city_id: int
    created_at: datetime
    is_taken: bool
    chat_enabled: bool
    address: Optional[str]
    visit_date: Optional[datetime]
    is_premium: Optional[bool]


# --- MACHINERY REQUESTS SCHEMAS ---
class MachineryRequestIn(BaseModel):
    """Схема для создания заявки на спецтехнику."""
    machinery_type: str
    description: str
    rental_price: float
    contact_info: str
    city_id: int
    rental_date: Optional[date] = None
    min_hours: int = 4

class MachineryRequestOut(BaseModel):
    """Схема для выдачи данных заявки на спецтехнику."""
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


# --- TOOL REQUESTS SCHEMAS ---
class ToolRequestIn(BaseModel):
    """Схема для создания заявки на инструмент."""
    tool_name: str
    description: str
    rental_price: float
    tool_count: int = 1
    rental_start_date: date
    rental_end_date: date
    contact_info: str
    has_delivery: bool = False
    delivery_address: Optional[str] = None
    city_id: int

class ToolRequestOut(BaseModel):
    """Схема для выдачи данных заявки на инструмент."""
    id: int
    user_id: int
    tool_name: str
    description: Optional[str]
    rental_price: float
    tool_count: int
    rental_start_date: date
    rental_end_date: date
    contact_info: str
    has_delivery: bool
    delivery_address: Optional[str]
    city_id: int
    created_at: datetime


# --- MATERIAL ADS SCHEMAS ---
class MaterialAdIn(BaseModel):
    """Схема для создания объявления о материалах."""
    material_type: str
    description: Optional[str]
    price: float
    contact_info: str
    city_id: int

class MaterialAdOut(BaseModel):
    """Схема для выдачи данных объявления о материалах."""
    id: int
    user_id: int
    material_type: str
    description: Optional[str]
    price: float
    contact_info: str
    city_id: int
    created_at: datetime
    is_premium: Optional[bool]


# --- UTILITY SCHEMAS ---
class SpecializationUpdate(BaseModel):
    specialization: str

class CityOut(BaseModel):
    id: int
    name: str

class ChatMessageIn(BaseModel):
    message: str

class ChatMessageOut(BaseModel):
    id: int
    request_id: int
    sender_id: int
    sender_username: str
    message: str
    timestamp: datetime

# --- СХЕМА ДЛЯ РЕЙТИНГА ---
class RatingIn(BaseModel):
    rating_value: int = Field(..., ge=1, le=5) # Оценка от 1 до 5


# ----------------------------------------------------
# --- API endpoints ---
# ----------------------------------------------------

@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Обработка логина и выдача JWT токена."""
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
        data={"sub": str(user["id"])}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@api_router.post("/register", response_model=UserOut)
async def create_user(user: UserIn):
    """Регистрация нового пользователя."""
    if user.user_type not in ["ЗАКАЗЧИК", "ИСПОЛНИТЕЛЬ"]:
        raise HTTPException(status_code=400, detail="Invalid user_type")

    if await is_email_taken(user.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail="Пользователь с таким email уже существует."
        )

    if user.user_type == "ИСПОЛНИТЕЛЬ" and not user.specialization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для типа 'ИСПОЛНИТЕЛЬ' поле 'specialization' обязательно."
        )

    specialization_to_insert = user.specialization if user.user_type == "ИСПОЛНИТЕЛЬ" else None

    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        email=user.email,
        hashed_password=hashed_password,
        user_type=user.user_type,
        phone_number=user.phone_number,
        specialization=specialization_to_insert,
        city_id=user.city_id,
        is_premium=False
    )
    
    last_record_id = await database.execute(query)
    created_user_query = users.select().where(users.c.id == last_record_id)
    created_user = await database.fetch_one(created_user_query)
    
    return {**created_user, "username": created_user["email"]}


@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """Получение данных текущего пользователя."""
    user_dict = dict(current_user)
    
    if user_dict.get("is_premium") is None:
        user_dict["is_premium"] = False 
        
    user_dict["username"] = user_dict["email"]
    return user_dict

# --- ИСПРАВЛЕНИЕ: Удалены дублирующиеся эндпоинты для чата ---
# Первая пара обработчиков чата была удалена, чтобы избежать конфликтов.
# Оставлены более специфичные эндпоинты, привязанные к /work_requests/{request_id}/chat,
# которые корректно используются фронтендом.

@api_router.post("/work_requests/{request_id}/rate")
async def rate_executor(request_id: int, rating: RatingIn, current_user: dict = Depends(get_current_user)):
    """Поставить оценку исполнителю по завершенной заявке."""
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(request_query)

    if not request:
        raise HTTPException(status_code=404, detail="Заявка на работу не найдена.")
    
    # Проверка: только заказчик может оценить
    if current_user["id"] != request["user_id"]:
        raise HTTPException(status_code=403, detail="Только заказчик может поставить оценку.")
    
    # Проверка: заявка должна быть взята в работу
    if not request["is_taken"] or request["executor_id"] is None:
        raise HTTPException(status_code=400, detail="Заявка должна быть взята в работу исполнителем.")
        
    executor_id = request["executor_id"]
    
    # 1. Получаем текущий рейтинг исполнителя
    executor_query = users.select().where(users.c.id == executor_id)
    executor = await database.fetch_one(executor_query)
    
    if not executor:
        raise HTTPException(status_code=404, detail="Исполнитель не найден.")
        
    # 2. Пересчитываем новый рейтинг
    old_total_rating = executor["rating"] * executor["rating_count"]
    new_rating_count = executor["rating_count"] + 1
    new_total_rating = old_total_rating + rating.rating_value
    new_average_rating = new_total_rating / new_rating_count
    
    # 3. Обновляем запись пользователя
    update_query = users.update().where(users.c.id == executor_id).values(
        rating=new_average_rating,
        rating_count=new_rating_count
    )
    await database.execute(update_query)
    
    return {"message": f"Исполнитель {executor['email']} успешно оценен. Новый средний рейтинг: {new_average_rating:.2f}", "new_rating": new_average_rating, "new_rating_count": new_rating_count}

@api_router.put("/users/update-specialization")
async def update_specialization(specialization_update: SpecializationUpdate, current_user: dict = Depends(get_current_user)):
    """Обновление специализации для ИСПОЛНИТЕЛЯ."""
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только ИСПОЛНИТЕЛЬ может обновлять специализацию")
    
    query = users.update().where(users.c.id == current_user["id"]).values(specialization=specialization_update.specialization)
    await database.execute(query)
    return {"message": "Специализация успешно обновлена"}


@api_router.post("/subscribe")
async def subscribe(current_user: dict = Depends(get_current_user)):
    """Активация премиум-подписки."""
    query = users.update().where(users.c.id == current_user["id"]).values(is_premium=True)
    await database.execute(query)
    return {"message": "Премиум-подписка успешно активирована!"}


@api_router.get("/cities/")
async def get_cities():
    """Получение списка городов."""
    query = cities.select()
    return await database.fetch_all(query)


# ----------------------------------------------------
# --- СПИСКИ ДЛЯ ФРОНТЕНДА ---
# ----------------------------------------------------
SPECIALIZATIONS_LIST = [
    "ЗЕМЛЯНЫЕ РАБОТЫ", "ФУНДАМЕНТЫ И ОСНОВАНИЯ", "КЛАДОЧНЫЕ РАБОТЫ",
    "МЕТАЛЛОКОНСТРУКЦИИ", "КРОВЕЛЬНЫЕ РАБОТЫ", "ОСТЕКЛЕНИЕ И ФАСАДНЫЕ РАБОТЫ",
    "ВНУТРЕННИЕ ИНЖЕНЕРНЫЕ СЕТИ", "САНТЕХНИЧЕСКИЕ И ВОДОПРОВОДНЫЕ РАБОТЫ",
    "ОТОПЛЕНИЕ И ТЕПЛОСНАБЖЕНИЕ", "ВЕНТИЛЯЦИЯ И КОНДИЦИОНИРОВАНИЕ",
    "ЭЛЕКТРОМОНТАЖНЫЕ РАБОТЫ", "ОТДЕЛОЧНЫЕ РАБОТЫ", "МОНТАЖ ПОТОЛКОВ",
    "ПОЛУСУХАЯ СТЯЖКА ПОЛА", "МАЛЯРНЫЕ РАБОТЫ", "БЛАГОУСТРОЙСТВО ТЕРРИТОРИИ",
    "СТРОИТЕЛЬСТВО ДОМОВ ПОД КЛЮЧ", "ДЕМОНТАЖНЫЕ РАБОТЫ", "МОНТАЖ ОБОРУДОВАНИЯ",
    "РАЗНОРАБОЧИЕ", "КЛИНИНГ, УБОРКА ПОМЕЩЕНИЙ", "МУЖ НА ЧАС",
    "БУРЕНИЕ, УСТРОЙСТВО СКВАЖИН", "ПРОЕКТИРОВАНИЕ", "ГЕОЛОГИЯ"
]

MACHINERY_TYPES = [
    "Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Трактор",
    "Манипулятор", "Бетононасос", "Ямобур", "Каток", "Фронтальный погрузчик",
    "Грейдер", "Эвакуатор", "Мини-погрузчик"
]

TOOLS_LIST = [
    "Бетономешалка", "Виброплита", "Генератор", "Компрессор", "Отбойный молоток",
    "Перфоратор", "Лазерный нивелир", "Бензопила", "Сварочный аппарат", "Шуруповерт",
    "Болгарка", "Строительный пылесос", "Тепловая пушка", "Мотобур", "Вибратор для бетона",
    "Рубанок", "Лобзик", "Торцовочная пила", "Краскопульт", "Штроборез",
    "Резчик швов", "Резчик кровли", "Шлифовальная машина", "Промышленный фен",
    "Домкрат", "Лебедка", "Плиткорез", "Камнерезный станок", "Отрезной станок",
    "Гидравлическая тележка", "Парогенератор", "Бытовка", "Кран Пионер", "Кран Умелец"
]

MATERIAL_TYPES = [
    "Цемент", "Песок", "Щебень", "Кирпич", "Бетон", "Армирующие материалы",
    "Гипсокартон", "Штукатурка", "Шпаклевка", "Краски", "Клей", "Грунтовка",
    "Плитка", "Линолеум", "Ламинат", "Паркет", "Фанера", "ОСБ", "Металлочерепица",
    "Профнастил", "Утеплитель", "Монтажная пена", "Деревянные брусья/доски"
]

@api_router.get("/specializations/")
def get_specializations():
    """Получение списка специализаций."""
    return SPECIALIZATIONS_LIST

@api_router.get("/machinery_types/")
def get_machinery_types():
    """Получение списка типов спецтехники."""
    return MACHINERY_TYPES

@api_router.get("/tools_list/")
def get_tools_list():
    """Получение списка инструментов."""
    return TOOLS_LIST

@api_router.get("/material_types/")
def get_material_types():
    """Получение списка типов материалов."""
    return MATERIAL_TYPES


# ----------------------------------------------------
# --- Work Requests Endpoints ---
# ----------------------------------------------------

@api_router.post("/work_requests", response_model=WorkRequestOut, status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    """Создание новой заявки на работу."""
    if current_user["user_type"] != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК может создавать заявки на работу")

    visit_date_data = request.visit_date
    if visit_date_data and visit_date_data.tzinfo is not None:
        visit_date_data = visit_date_data.replace(tzinfo=None)

    query = work_requests.insert().values(
        user_id=current_user["id"],
        name=request.name,
        description=request.description,
        specialization=request.specialization,
        budget=request.budget,
        phone_number=request.phone_number,
        city_id=request.city_id,
        address=request.address,
        visit_date=visit_date_data,
        is_premium=current_user["is_premium"],
        is_taken=False,
        chat_enabled=False
    )
    last_record_id = await database.execute(query)
    created_request_query = work_requests.select().where(work_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    return created_request

@api_router.get("/work_requests/{request_id}", response_model=WorkRequestOut)
async def get_single_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    """Получение данных одной заявки по ID."""
    query = work_requests.select().where(work_requests.c.id == request_id)
    request_item = await database.fetch_one(query)

    if not request_item:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    return request_item

@api_router.get("/work_requests/by_city/{city_id}", response_model=List[WorkRequestOut])
async def get_work_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех заявок в определенном городе."""
    query = work_requests.select().where((work_requests.c.city_id == city_id))
    return await database.fetch_all(query)


@api_router.get("/work_requests/my", response_model=List[WorkRequestOut])
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    """Получение заявок, созданных текущим пользователем (Заказчиком)."""
    query = work_requests.select().where(work_requests.c.user_id == current_user["id"])
    return await database.fetch_all(query)
    

@api_router.get("/work_requests/taken", response_model=List[WorkRequestOut])
async def get_my_taken_work_requests(current_user: dict = Depends(get_current_user)):
    """Получение заявок, принятых текущим пользователем (Исполнителем)."""
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        return []
    query = work_requests.select().where(work_requests.c.executor_id == current_user["id"])
    return await database.fetch_all(query)


@api_router.post("/work_requests/{request_id}/take", status_code=status.HTTP_200_OK)
async def take_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    """Принятие заявки на работу исполнителем."""
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только ИСПОЛНИТЕЛЬ может принимать заявки")
    
    async with database.transaction():
        request_query = work_requests.select().where(work_requests.c.id == request_id)
        request_item = await database.fetch_one(request_query)

        if not request_item:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if request_item["is_taken"]:
            raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем")

        update_query = work_requests.update().where(work_requests.c.id == request_id).values(
            is_taken=True,
            executor_id=current_user["id"],
            chat_enabled=True
        )
        await database.execute(update_query)
    
    return {"message": "Вы успешно приняли заявку и можете начать чат с заказчиком."}


# ----------------------------------------------------
# --- Chat Endpoints ---
# ----------------------------------------------------

@api_router.get("/work_requests/{request_id}/chat", response_model=List[ChatMessageOut])
async def get_chat_messages(request_id: int, current_user: dict = Depends(get_current_user)):
    """Получение истории сообщений для чата по заявке."""
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_item = await database.fetch_one(request_query)

    if not request_item:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    is_owner = request_item["user_id"] == current_user["id"]
    is_executor = request_item["executor_id"] == current_user["id"]

    if not (is_owner or is_executor):
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому чату")
    
    if not request_item["chat_enabled"]:
        raise HTTPException(status_code=400, detail="Чат для этой заявки не активирован")

    query = """
    SELECT cm.id, cm.request_id, cm.sender_id, cm.message, cm.timestamp, u.email as sender_username
    FROM chat_messages cm
    JOIN users u ON cm.sender_id = u.id
    WHERE cm.request_id = :request_id
    ORDER BY cm.timestamp
    """
    messages = await database.fetch_all(query, values={"request_id": request_id})
    return messages


@api_router.post("/work_requests/{request_id}/chat", status_code=status.HTTP_201_CREATED)
async def send_chat_message(request_id: int, message: ChatMessageIn, current_user: dict = Depends(get_current_user)):
    """Отправка нового сообщения в чат."""
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_item = await database.fetch_one(request_query)

    if not request_item:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    is_owner = request_item["user_id"] == current_user["id"]
    is_executor = request_item["executor_id"] == current_user["id"]

    if not (is_owner or is_executor):
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому чату")

    if not request_item["chat_enabled"]:
        raise HTTPException(status_code=400, detail="Чат для этой заявки не активирован")

    query = chat_messages.insert().values(
        request_id=request_id,
        sender_id=current_user["id"],
        message=message.message
    )
    await database.execute(query)
    
    return {"message": "Сообщение отправлено"}


# ----------------------------------------------------
# --- Machinery Requests Endpoints ---
# ----------------------------------------------------

@api_router.post("/machinery_requests", response_model=MachineryRequestOut, status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    """Создание новой заявки на спецтехнику."""
    query = machinery_requests.insert().values(
        user_id=current_user["id"],
        machinery_type=request.machinery_type,
        description=request.description,
        rental_date=request.rental_date,
        min_hours=request.min_hours,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=request.city_id,
        is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    created_request_query = machinery_requests.select().where(machinery_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    return created_request


@api_router.get("/machinery_requests/by_city/{city_id}", response_model=List[MachineryRequestOut])
async def get_machinery_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех заявок на спецтехнику в определенном городе."""
    query = machinery_requests.select().where(machinery_requests.c.city_id == city_id)
    return await database.fetch_all(query)


@api_router.get("/machinery_requests/my", response_model=List[MachineryRequestOut])
async def get_my_machinery_requests(current_user: dict = Depends(get_current_user)):
    """Получение заявок на спецтехнику, созданных текущим пользователем."""
    query = machinery_requests.select().where(machinery_requests.c.user_id == current_user["id"])
    return await database.fetch_all(query)


# ----------------------------------------------------
# --- Tool Requests Endpoints ---
# ----------------------------------------------------

@api_router.post("/tool_requests", response_model=ToolRequestOut, status_code=status.HTTP_201_CREATED)
async def create_tool_request(request: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    """Создание новой заявки на инструмент."""
    query = tool_requests.insert().values(
        user_id=current_user["id"],
        tool_name=request.tool_name,
        description=request.description,
        rental_price=request.rental_price,
        tool_count=request.tool_count,
        rental_start_date=request.rental_start_date,
        rental_end_date=request.rental_end_date,
        contact_info=request.contact_info,
        has_delivery=request.has_delivery,
        delivery_address=request.delivery_address,
        city_id=request.city_id
    )
    last_record_id = await database.execute(query)
    created_request_query = tool_requests.select().where(tool_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    return created_request


@api_router.get("/tool_requests/by_city/{city_id}", response_model=List[ToolRequestOut])
async def get_tool_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех заявок на инструмент в определенном городе."""
    query = tool_requests.select().where(tool_requests.c.city_id == city_id)
    return await database.fetch_all(query)


@api_router.get("/tool_requests/my", response_model=List[ToolRequestOut])
async def get_my_tool_requests(current_user: dict = Depends(get_current_user)):
    """Получение заявок на инструмент, созданных текущим пользователем."""
    query = tool_requests.select().where(tool_requests.c.user_id == current_user["id"])
    return await database.fetch_all(query)


# ----------------------------------------------------
# --- Material Ads Endpoints ---
# ----------------------------------------------------

@api_router.post("/material_ads", response_model=MaterialAdOut, status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    """Создание нового объявления о продаже/покупке материалов."""
    query = material_ads.insert().values(
        user_id=current_user["id"],
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        contact_info=ad.contact_info,
        city_id=ad.city_id,
        is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    created_ad_query = material_ads.select().where(material_ads.c.id == last_record_id)
    created_ad = await database.fetch_one(created_ad_query)
    return created_ad


@api_router.get("/material_ads/by_city/{city_id}", response_model=List[MaterialAdOut])
async def get_material_ads_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех объявлений о материалах в определенном городе."""
    query = material_ads.select().where(material_ads.c.city_id == city_id)
    return await database.fetch_all(query)


@api_router.get("/material_ads/my", response_model=List[MaterialAdOut])
async def get_my_material_ads(current_user: dict = Depends(get_current_user)):
    """Получение объявлений о материалах, созданных текущим пользователем."""
    query = material_ads.select().where(material_ads.c.user_id == current_user["id"])
    return await database.fetch_all(query)


# ----------------------------------------------------
# --- Static Files Mounting ---
# ----------------------------------------------------
app.include_router(api_router)

# Обслуживание статических файлов и главной страницы
# Этот блок должен быть в конце, после подключения роутера
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")

    @app.get("/")
    async def read_index():
        return FileResponse(static_path / "index.html")
else:
    # Удалено уведомление, чтобы не создавать лишний вывод в логах
    pass