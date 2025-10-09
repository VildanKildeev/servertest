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
from sqlalchemy.sql import select
import os
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.sql import select 


# --- Database setup ---
# Импортируем все таблицы и метаданды из файла database.py
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities, database

load_dotenv()

# --- ИСПРАВЛЕНИЕ ПУТЕЙ ДЛЯ СТАТИЧЕСКИХ ФАЙЛОВ ---
# Находим корневую папку проекта
base_path = Path(__file__).parent
# Определяем путь к папке static
static_path = base_path / "static"
# ------------------------------------------------

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
    allow_origins=["*", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ИСПРАВЛЕНИЕ 2: Монтирование папки static ---
# Монтируем папку static под префиксом /static
app.mount("/static", StaticFiles(directory=static_path), name="static")
# ------------------------------------------------

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    print("Database connected and tables checked/created.")
    # ИСПРАВЛЕНИЕ: Разделяем синхронный и асинхронный код
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE"))

    # --- КОД ДЛЯ ЗАПОЛНЕНИЯ ГОРОДОВ ---
    query = cities.select().limit(1)
    city_exists = await database.fetch_one(query)

    if not city_exists:
        print("Города не найдены, добавляю стандартный список...")
        default_cities = [
            {"name": "Москва"},
            {"name": "Санкт-Петербург"},
            {"name": "Новосибирск"},
            {"name": "Екатеринбург"},
            {"name": "Казань"},
            {"name": "Нижний Новгород"},
            {"name": "Челябинск"},
            {"name": "Самара"},
            {"name": "Омск"},
            {"name": "Ростов-на-Дону"},
        ]
        insert_query = cities.insert().values(default_cities)
        await database.execute(insert_query)
        print("Города успешно добавлены.")
    # --- КОНЕЦ КОДА ---

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("Database disconnected.")

# Схемы Pydantic для валидации данных

# НОВАЯ И ОБНОВЛЕННАЯ модель для создания пользователя
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    phone_number: str
    user_type: str = Field(..., description="Тип пользователя: ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ")
    specialization: Optional[str] = None

# Модель для пользователя, который хранится в БД
class UserInDB(BaseModel):
    id: int
    email: str
    hashed_password: str
    phone_number: str
    is_active: bool = True
    user_type: str
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False  # ✅ ИСПРАВЛЕНО: Теперь разрешен None из БД
    class Config: from_attributes = True

class UserOut(BaseModel):
    id: int
    email: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False  # ✅ ИСПРАВЛЕНО: Теперь разрешен None из БД
    city_id: Optional[int] = None # <-- Ожидаемое поле
    class Config: from_attributes = True
        
class UserUpdate(BaseModel):
    user_name: Optional[str] = None
    email: Optional[str] = None
    user_type: Optional[str] = None
    specialization: Optional[str] = None
    is_premium: Optional[bool] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None

# Схемы для работы
class WorkRequestIn(BaseModel):
    description: str
    specialization: str
    budget: float
    contact_info: str
    city_id: int
    is_premium: bool = False
    is_master_visit_required: bool = False

class WorkRequestUpdate(BaseModel):
    description: Optional[str] = None
    specialization: Optional[str] = None
    budget: Optional[float] = None
    contact_info: Optional[str] = None
    city_id: Optional[int] = None
    is_premium: Optional[bool] = None
    executor_id: Optional[int] = None
    status: Optional[str] = None

# Схемы для спецтехники (ОБНОВЛЕНО)
class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    is_premium: bool = False
    # --- НОВЫЕ ПОЛЯ ---
    rental_date: Optional[date] = None
    min_rental_hours: int = 4
    has_delivery: bool = False
    delivery_address: Optional[str] = None

# Схемы для инструмента
class ToolRequestIn(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    count: int = 1
    rental_start_date: Optional[date] = None
    rental_end_date: Optional[date] = None
    has_delivery: bool = False
    delivery_address: Optional[str] = None

# Схемы для материалов
class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int
    is_premium: bool = False

# Схемы для города
class City(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

# Хэширование пароля
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# Функция для аутентификации пользователя
async def authenticate_user(username: str, password: str):
    query = users.select().where(users.c.email == username)
    user_db = await database.fetch_one(query)
    if not user_db:
        return False
    if not verify_password(password, user_db["hashed_password"]):
        return False
    return user_db

# --- ИСПРАВЛЕНИЕ: Новые вспомогательные функции для авторизации и опциональной зависимости ---

# Helper to parse token and fetch user data
async def get_user_from_token(token: str) -> Optional[dict]:
    """Извлекает данные пользователя из JWT-токена, ищет в БД по email."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # Токен содержит email в поле "sub"
        email: str = payload.get("sub") 
        if email is None:
            return None
        
        # --- ИСПРАВЛЕНИЕ: Ищем пользователя по EMAIL ---
        query = select(users).where(users.c.email == email)
        user_data = await database.fetch_one(query)
        
        return dict(user_data) if user_data else None
    except JWTError:
        return None
    except Exception:
        return None

# 1. Защищенная зависимость (вызывает 401, если нет токена/невалиден)
async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    user = await get_user_from_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

# Вспомогательная функция для получения токена из заголовка без авто-ошибки 401
async def get_optional_token(request: Request) -> Optional[str]:
    """Извлекает токен 'Bearer' из заголовка Authorization."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    return None

# 2. Публичная зависимость с опциональным пользователем (возвращает None, если нет токена/невалиден)
async def get_optional_user(token: Optional[str] = Depends(get_optional_token)) -> Optional[dict]:
    """Возвращает данные пользователя, если токен предоставлен и валиден, иначе возвращает None."""
    if not token:
        return None
    return await get_user_from_token(token)

# --- КОНЕЦ ИСПРАВЛЕНИЯ ЗАВИСИМОСТЕЙ ---


# Создание токена
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- Маршруты API ---

# --- ИСПРАВЛЕНИЕ 3: Корневой маршрут (Главная страница) ---
@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_index():
    # Файл index.html ищется в папке 'static'
    return FileResponse(static_path / "index.html")
# -----------------------------------------------------------


# НОВЫЙ МАРШРУТ для получения токена
@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user_db = await authenticate_user(form_data.username, form_data.password)
    
    if not user_db:
        # Аутентификация не удалась
        raise HTTPException( 
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 🌟 ИСПРАВЛЕНИЕ: Этот блок должен быть без отступа (на уровне if)
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user_db["email"])}, # Используем email для поиска пользователя
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
     

# НОВЫЙ МАРШРУТ для получения профиля пользователя
@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user

# --- Helper function for email check ---
async def is_email_taken(email: str):
    query = users.select().where(users.c.email == email)
    existing_user = await database.fetch_one(query)
    return existing_user is not None

# ИСПРАВЛЕНИЕ: Путь изменен на /register для соответствия фронтенду
@api_router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def create_user(user: UserCreate, background_tasks: BackgroundTasks):
    try:
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
        hashed_password = get_password_hash(user.password)
        query = users.insert().values(
            email=user.email,
            hashed_password=hashed_password,
            phone_number=user.phone_number,
            user_type=user.user_type,
            specialization=user.specialization
        )
        last_record_id = await database.execute(query)
        user_in_db_query = users.select().where(users.c.id == last_record_id)
        user_in_db = await database.fetch_one(user_in_db_query)
        
        return user_in_db
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Пользователь с таким email уже существует."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Произошла ошибка сервера: {e}"
        )

# Создание запроса на работу
@api_router.post("/work_requests/", status_code=status.HTTP_201_CREATED)
async def create_work_request(work_request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = work_requests.insert().values(
        user_id=user_id,
        description=work_request.description,
        specialization=work_request.specialization,
        budget=work_request.budget,
        contact_info=work_request.contact_info,
        city_id=work_request.city_id,
        is_premium=work_request.is_premium,
        is_master_visit_required=work_request.is_master_visit_required
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **work_request.dict()}

# --- ИСПРАВЛЕННЫЙ МАРШРУТ для получения всех заявок на работу ---
@api_router.get("/work_requests/")
async def get_work_requests(
    # Позволяем ручную фильтрацию по city_id
    city_id: Optional[int] = None, 
    # Используем опциональную зависимость
    current_user: Optional[dict] = Depends(get_optional_user) 
):
    query = work_requests.select()
    filter_city_id = None
    
    # 1. Приоритет: Город авторизованного пользователя
    if current_user and current_user.get('city_id') is not None:
        filter_city_id = current_user.get('city_id')
        
    # 2. Иначе: Город из параметра запроса (для неавторизованных или ручного поиска)
    elif city_id is not None:
        filter_city_id = city_id

    # Применяем фильтр
    if filter_city_id is not None:
        query = query.where(work_requests.c.city_id == filter_city_id)
        
    requests = await database.fetch_all(query)
    return requests
# -----------------------------------------------------------------


# Создание заявки на спецтехнику (ОБНОВЛЕНО)
@api_router.post("/machinery_requests/", status_code=status.HTTP_201_CREATED)
async def create_machinery_request(machinery_request: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = machinery_requests.insert().values(
        user_id=user_id,
        machinery_type=machinery_request.machinery_type,
        description=machinery_request.description,
        rental_price=machinery_request.rental_price,
        contact_info=machinery_request.contact_info,
        city_id=machinery_request.city_id,
        is_premium=machinery_request.is_premium,
        rental_date=machinery_request.rental_date,
        min_rental_hours=machinery_request.min_rental_hours,
        has_delivery=machinery_request.has_delivery,
        delivery_address=machinery_request.delivery_address
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **machinery_request.dict()}

# --- ИСПРАВЛЕННЫЙ МАРШРУТ для получения всех заявок на спецтехнику ---
@api_router.get("/machinery_requests/")
async def get_machinery_requests(
    city_id: Optional[int] = None, 
    current_user: Optional[dict] = Depends(get_optional_user) 
):
    query = machinery_requests.select()
    filter_city_id = None
    
    # 1. Приоритет: Город авторизованного пользователя
    if current_user and current_user.get('city_id') is not None:
        filter_city_id = current_user.get('city_id')
        
    # 2. Иначе: Город из параметра запроса
    elif city_id is not None:
        filter_city_id = city_id

    # Применяем фильтр
    if filter_city_id is not None:
        query = query.where(machinery_requests.c.city_id == filter_city_id)

    requests = await database.fetch_all(query)
    return requests
# -----------------------------------------------------------------

# Создание заявки на инструмент
@api_router.post("/tool_requests/", status_code=status.HTTP_201_CREATED)
async def create_tool_request(tool_request: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = tool_requests.insert().values(
        user_id=user_id,
        tool_name=tool_request.tool_name,
        description=tool_request.description,
        rental_price=tool_request.rental_price,
        contact_info=tool_request.contact_info,
        city_id=tool_request.city_id,
        count=tool_request.count,
        rental_start_date=tool_request.rental_start_date,
        rental_end_date=tool_request.rental_end_date,
        has_delivery=tool_request.has_delivery,
        delivery_address=tool_request.delivery_address
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **tool_request.dict()}

# --- ИСПРАВЛЕННЫЙ МАРШРУТ для получения всех заявок на инструмент ---
@api_router.get("/tool_requests/")
async def get_tool_requests(
    city_id: Optional[int] = None,
    current_user: Optional[dict] = Depends(get_optional_user)
):
    query = tool_requests.select()
    filter_city_id = None
    
    # 1. Приоритет: Город авторизованного пользователя
    if current_user and current_user.get('city_id') is not None:
        filter_city_id = current_user.get('city_id')
        
    # 2. Иначе: Город из параметра запроса
    elif city_id is not None:
        filter_city_id = city_id

    # Применяем фильтр
    if filter_city_id is not None:
        query = query.where(tool_requests.c.city_id == filter_city_id)
        
    requests = await database.fetch_all(query)
    return requests
# -----------------------------------------------------------------

# Создание объявления о материалах
@api_router.post("/material_ads/", status_code=status.HTTP_201_CREATED)
async def create_material_ad(material_ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = material_ads.insert().values(
        user_id=user_id,
        material_type=material_ad.material_type,
        description=material_ad.description,
        price=material_ad.price,
        contact_info=material_ad.contact_info,
        city_id=material_ad.city_id,
        is_premium=material_ad.is_premium
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **material_ad.dict()}

# --- ИСПРАВЛЕННЫЙ МАРШРУТ для получения всех объявлений о материалах ---
@api_router.get("/material_ads/")
async def get_material_ads(
    city_id: Optional[int] = None,
    current_user: Optional[dict] = Depends(get_optional_user)
):
    query = material_ads.select()
    filter_city_id = None
    
    # 1. Приоритет: Город авторизованного пользователя
    if current_user and current_user.get('city_id') is not None:
        filter_city_id = current_user.get('city_id')
        
    # 2. Иначе: Город из параметра запроса
    elif city_id is not None:
        filter_city_id = city_id

    # Применяем фильтр
    if filter_city_id is not None:
        query = query.where(material_ads.c.city_id == filter_city_id)
        
    requests = await database.fetch_all(query)
    return requests
# -----------------------------------------------------------------


# --- Маршруты для получения данных из таблиц-справочников ---
# Список специализаций
SPECIALIZATIONS = [
    "Электрик", "Сантехник", "Сварщик", "Плиточник", "Маляр", "Штукатур",
    "Ремонтник", "Плотник", "Кровельщик", "Каменщик", "Фасадчик",
    "Отделочник", "Монтажник", "Демонтажник", "Разнорабочий",
    "Специалист по полам", "Установщик дверей/окон", "Мебельщик", "Сборщик мебели",
    "Специалист по вентиляции", "Геодезист", "Ландшафтный дизайнер", "Уборщик",
    "Косметический ремонт", "Капитальный ремонт", "Проектирование"
]

@api_router.get("/specializations/")
def get_specializations():
    return SPECIALIZATIONS

# Список типов спецтехники
MACHINERY_TYPES = [
    "Экскаватор", "Погрузчик", "Манипулятор", "Дорожный каток", "Самосвал", "Автокран", "Автовышка",
    "Мусоровоз", "Илосос", "Канистра", "Монтажный пистолет", "Когти монтерские", "Монтажный пояс",
    "Электростанция", "Осветительные мачты", "Генератор", "Компрессор", "Мотопомпа",
    "Сварочный аппарат", "Паяльник", "Гайковерт", "Пресс", "Болгарка", "Дрель", "Перфоратор",
    "Виброплита", "Вибротрамбовка", "Виброрейка", "Вибратор для бетона", "Затирочная машина",
    "Резчик швов", "Резчик кровли", "Шлифовальная машина", "Промышленный фен", "Промышленный пылесос",
    "Бетономешалка", "Растворосмеситель", "Пескоструйный аппарат", "Опрессовщик", "Прочистная машина", "Пневмоподатчик", "Штукатурная машина",
    "Окрасочный аппарат", "Компрессорный агрегат", "Гидронасос", "Электроталь",
    "Тепловые пушки", "Дизельные тепловые пушки", "Теплогенераторы", "Осушители воздуха", "Прогрев грунта", "Промышленные вентиляторы",
    "Парогенератор", "Бытовки", "Кран Пионер", "Кран Умелец", "Ручная таль", "Домкраты", "Тележки гидравлические", "Лебедки",
    "Коленчатый подъемник", "Фасадный подъемник", "Телескопический подъемник", "Ножничный подъемник", "Штабелер",
    "Установка алмазного бурения", "Сантехническое оборудование", "Окрасочный аппарат", "Кровельное оборудование",
    "Электромонтажный инструмент", "Резьбонарезной инструмент", "Газорезочное оборудование", "Инструмент для фальцевой кровли",
    "Растворные станции", "Труборезы", "Оборудование для получения лицензии МЧС", "Оборудование для работы с композитом",
    "Рейсмусовый станок", "Дрель на магнитной подошве", "Плиткорезы", "Отрезной станок", "Фрезер", "Камнерезные станки"
]

@api_router.get("/machinery_types/")
def get_machinery_types():
    return MACHINERY_TYPES
    
# Список инструментов
TOOLS_LIST = [
    "Бетономешалка", "Виброплита", "Генератор", "Компрессор", "Отбойный молоток",
    "Перфоратор", "Лазерный нивелир", "Бензопила", "Сварочный аппарат", "Шуруповерт",
    "Болгарка", "Строительный пылесос", "Тепловая пушка", "Мотобур", "Вибратор для бетона",
    "Рубанок", "Лобзик", "Торцовочная пила", "Краскопульт", "Штроборез",
    "Резчик швов", "Резчик кровли", "Шлифовальная машина", "Промышленный фен",
    "Домкрат", "Лебедка", "Плиткорез", "Камнерезный станок", "Отрезной станок",
    "Гидравлическая тележка", "Парогенератор", "Бытовка", "Кран Пионер", "Кран Умелец"
]

@api_router.get("/tools_list/")
def get_tools_list():
    return TOOLS_LIST

# Список типов материалов
MATERIAL_TYPES = [
    "Цемент", "Песок", "Щебень", "Кирпич", "Бетон", "Армирующие материалы",
    "Гипсокартон", "Штукатурка", "Шпаклевка", "Краски", "Клей", "Грунтовка"
]

@api_router.get("/material_types/")
def get_material_types():
    return MATERIAL_TYPES
    
@api_router.get("/cities/")
async def get_cities():
    query = cities.select().order_by(cities.c.name)
    all_cities = await database.fetch_all(query)
    return all_cities

# ИСПРАВЛЕНИЕ: Маршруты "Мои заявки" остаются защищенными
@api_router.get("/my/work_requests")
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    work_query = work_requests.select().where(work_requests.c.user_id == user_id)
    return await database.fetch_all(work_query)

@api_router.get("/my/machinery_requests")
async def get_my_machinery_requests(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == user_id)
    return await database.fetch_all(machinery_query)

@api_router.get("/my/tool_requests")
async def get_my_tool_requests(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    tool_query = tool_requests.select().where(tool_requests.c.user_id == user_id)
    return await database.fetch_all(tool_query)

@api_router.get("/my/material_ads")
async def get_my_material_ads(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    material_query = material_ads.select().where(material_ads.c.user_id == user_id)
    return await database.fetch_all(material_query)


# Новый маршрут для принятия заявки
@api_router.patch("/work_requests/{request_id}/take")
async def take_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    
    # Проверяем, что заявка существует
    query_check = select(work_requests).where(work_requests.c.id == request_id)
    request_data = await database.fetch_one(query_check)
    if not request_data:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    # Проверяем, что заявка не уже взята
    if request_data['status'] != 'active': # Используем 'active' как в таблице
        raise HTTPException(status_code=400, detail="Эта заявка уже принята или закрыта.")

    # Обновляем статус и исполнителя
    query_update = work_requests.update().where(work_requests.c.id == request_id).values(status="В РАБОТЕ", executor_id=user_id)
    await database.execute(query_update)
    
    return {"message": "Заявка успешно принята.", "request_id": request_id}

@api_router.patch("/machinery_requests/{request_id}/take")
async def take_machinery_request(request_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    
    # 1. Проверяем, что заявка существует
    query_check = select(machinery_requests).where(machinery_requests.c.id == request_id)
    request_data = await database.fetch_one(query_check)
    if not request_data:
        raise HTTPException(status_code=404, detail="Заявка на технику не найдена.")

    # 2. Проверяем, что заявка не уже взята
    if request_data['status'] != 'active':
        raise HTTPException(status_code=400, detail="Эта заявка уже принята или закрыта.")

    # 3. Обновляем статус и исполнителя
    query_update = machinery_requests.update().where(machinery_requests.c.id == request_id).values(status="В РАБОТЕ", executor_id=user_id)
    await database.execute(query_update)
    
    return {"message": "Заявка на технику успешно принята.", "request_id": request_id}

# Новый маршрут для подписки на премиум
@api_router.post("/subscribe/")
async def activate_premium_subscription(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = users.update().where(users.c.id == user_id).values(is_premium=True)
    await database.execute(query)
    return {"message": "Премиум-подписка активирована. Вы можете разместить до 5 премиум-заявок."}

# Новый маршрут для обновления специализации
@api_router.post("/update_specialization/")
async def update_user_specialization(specialization: str, current_user: dict = Depends(get_current_user)):
    """Обновляет поле 'specialization' для текущего пользователя."""
    user_id = current_user["id"]
    
    # Проверка, что пользователь - ИСПОЛНИТЕЛЬ
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только ИСПОЛНИТЕЛИ могут менять специализацию.")
    
    query = users.update().where(users.c.id == user_id).values(specialization=specialization)
    await database.execute(query)
    
    return {"message": "Специализация обновлена."}

app.include_router(api_router)