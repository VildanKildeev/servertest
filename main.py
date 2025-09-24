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
# Импортируем все таблицы и метаданды из файла database.py
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities, database

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
    allow_origins=["*", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    print("Database connected and tables checked/created.")

    # --- НОВЫЙ КОД ДЛЯ ЗАПОЛНЕНИЯ ГОРОДОВ ---
    # Проверяем, есть ли города в таблице
    query = cities.select().limit(1)
    city_exists = await database.fetch_one(query)

    # Если городов нет, добавляем их
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
    # --- КОНЕЦ НОВОГО КОДА ---

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("Database disconnected.")

# Схемы Pydantic для валидации данных

# НОВАЯ И ОБНОВЛЕННАЯ модель для создания пользователя
class UserCreate(BaseModel):
    name: str # ДОБАВЛЕННОЕ ПОЛЕ
    email: EmailStr
    password: str
    phone_number: str
    user_type: str = Field(..., description="Тип пользователя: ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ")
    specialization: Optional[str] = None
    city_id: Optional[int] = None # ДОБАВЛЕНОЕ ПОЛЕ

# Модель для пользователя, который хранится в БД
class UserInDB(BaseModel):
    id: int
    email: str
    hashed_password: str
    phone_number: str
    is_active: bool = True
    user_type: str
    specialization: Optional[str] = None
    
    class Config:
        from_attributes = True

# Модель для отображения пользователя (обновлена)
class UserOut(BaseModel):
    id: int
    name: str # ДОБАВЛЕННОЕ ПОЛЕ
    email: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None
    city: Optional[dict] = None # ДОБАВЛЕНОЕ ПОЛЕ

    class Config:
        from_attributes = True
        
class UserUpdate(BaseModel):
    user_name: Optional[str] = None
    email: Optional[str] = None
    user_type: Optional[str] = None
    specialization: Optional[str] = None
    is_premium: Optional[bool] = None
    city_id: Optional[int] = None # ДОБАВЛЕННОЕ ПОЛЕ

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

# Проверка пользователя
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(username=email)
    except JWTError:
        raise credentials_exception

    query = users.select().where(users.c.email == token_data.username)
    user_db = await database.fetch_one(query)
    if user_db is None:
        raise credentials_exception
    return user_db

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

# Определяем базовый путь
base_path = Path(__file__).parent
static_path = base_path / "static"

# Указываем FastAPI, где искать статические файлы
app.mount("/static", StaticFiles(directory=static_path), name="static")

@app.get("/", response_class=FileResponse)
async def serve_index():
    return FileResponse(static_path / "index.html")

# НОВЫЙ МАРШРУТ для получения токена
@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user_db = await authenticate_user(form_data.username, form_data.password)
    if not user_db:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_db["email"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    # Получаем информацию о городе пользователя
    query = users.join(cities).select().where(users.c.id == current_user["id"])
    user_with_city = await database.fetch_one(query)

    if user_with_city:
        user_data = dict(user_with_city)
        # Формируем данные для ответа
        user_out = UserOut(
            id=user_data["id"],
            name=user_data["name"], # ДОБАВЛЕННЫЙ ПАРАМЕТР
            email=user_data["email"],
            phone_number=user_data["phone_number"],
            user_type=user_data["user_type"],
            specialization=user_data["specialization"],
            city={"id": user_data["city_id"], "name": user_data["name_1"]} # имя столбца "name" из таблицы "cities" будет "name_1"
        )
        return user_out
    else:
        return UserOut(**current_user, city=None)

# --- Helper function for email check ---
async def is_email_taken(email: str):
    query = users.select().where(users.c.email == email)
    existing_user = await database.fetch_one(query)
    return existing_user is not None

@api_router.put("/users/me", response_model=UserOut)
async def update_users_me(user_update: UserUpdate, current_user: dict = Depends(get_current_user)):
    if user_update.user_name:
        query = users.update().where(users.c.id == current_user["id"]).values(name=user_update.user_name)
        await database.execute(query)
    if user_update.city_id:
        query = users.update().where(users.c.id == current_user["id"]).values(city_id=user_update.city_id)
        await database.execute(query)

    # Перезагружаем пользователя, чтобы вернуть обновленные данные
    return await read_users_me(current_user=current_user)

@api_router.post("/users/", status_code=status.HTTP_201_CREATED, response_model=UserOut)
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
        
        hashed_password = pwd_context.hash(user.password)
        query = users.insert().values(
            name=user.name,
            email=user.email,
            hashed_password=hashed_password,
            phone_number=user.phone_number,
            user_type=user.user_type,
            specialization=user.specialization,
            city_id=user.city_id
        )
        last_record_id = await database.execute(query)
        user_in_db = await database.fetch_one(users.select().where(users.c.id == last_record_id))
        
        return UserOut(
            id=user_in_db["id"],
            name=user_in_db["name"],
            email=user_in_db["email"],
            phone_number=user_in_db["phone_number"],
            user_type=user_in_db["user_type"],
            specialization=user_in_db["specialization"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Произошла ошибка сервера: {str(e)}")
        
        # Создание токена
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        token_data = {"sub": user_in_db["email"], "id": user_in_db["id"]}
        access_token = create_access_token(data=token_data, expires_delta=access_token_expires)

        # Вы можете добавить здесь фоновое задание для отправки email, если функция `send_welcome_email` определена
        # background_tasks.add_task(send_welcome_email, user.email)

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
        is_premium=work_request.is_premium
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **work_request.dict()}

# Получение всех заявок на работу
@api_router.get("/work_requests/")
async def get_work_requests():
    query = work_requests.select()
    requests = await database.fetch_all(query)
    return requests

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
        # --- НОВЫЕ ПОЛЯ ---
        rental_date=machinery_request.rental_date,
        min_rental_hours=machinery_request.min_rental_hours
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **machinery_request.dict()}

# Получение всех заявок на спецтехнику
@api_router.get("/machinery_requests/")
async def get_machinery_requests():
    query = machinery_requests.select()
    requests = await database.fetch_all(query)
    return requests

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

# Получение всех заявок на инструмент
@api_router.get("/tool_requests/")
async def get_tool_requests():
    query = tool_requests.select()
    requests = await database.fetch_all(query)
    return requests

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

# Получение всех объявлений о материалах
@api_router.get("/material_ads/")
async def get_material_ads():
    query = material_ads.select()
    ads = await database.fetch_all(query)
    return ads

@api_router.get("/users/me/requests/")
async def get_my_requests(
    city_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    all_requests = []
    
    # Запросы на работы
    work_query = work_requests.select().where(work_requests.c.user_id == current_user["id"])
    if city_id:
        work_query = work_query.where(work_requests.c.city_id == city_id)
    work_requests_from_db = await database.fetch_all(work_query)
    all_requests.extend([
        {**dict(req), "type": "work"} for req in work_requests_from_db
    ])

    # Запросы на аренду спецтехники
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == current_user["id"])
    if city_id:
        machinery_query = machinery_query.where(machinery_requests.c.city_id == city_id)
    machinery_requests_from_db = await database.fetch_all(machinery_query)
    all_requests.extend([
        {**dict(req), "type": "machinery"} for req in machinery_requests_from_db
    ])

    # Запросы на аренду инструментов
    tool_query = tool_requests.select().where(tool_requests.c.user_id == current_user["id"])
    if city_id:
        tool_query = tool_query.where(tool_requests.c.city_id == city_id)
    tool_requests_from_db = await database.fetch_all(tool_query)
    all_requests.extend([
        {**dict(req), "type": "tool"} for req in tool_requests_from_db
    ])

    # Возвращаем все найденные заявки
    return {"requests": all_requests}

# Маршруты для получения списков специализаций, городов, типов техники и инструментов
@api_router.get("/cities/")
async def get_cities():
    query = cities.select()
    all_cities = await database.fetch_all(query)
    return all_cities

SPECIALIZATIONS = [
    "Электрик", "Сантехник", "Плотник", "Маляр", "Кровельщик", "Сварщик", "Разнорабочий",
    "Ремонт бытовой техники", "Установка дверей", "Установка окон", "Дизайнер интерьеров",
    "Прораб", "Плиточник", "Сборщик мебели", "Отделочные работы", "Демонтажные работы",
    "Каменщик", "Фасадные работы", "Укладка пола", "Ландшафтный дизайн", "Монолитные работы",
    "Кладка кирпича", "Бетонные работы", "Обустройство скважин"
]

@api_router.get("/specializations/")
def get_specializations():
    return SPECIALIZATIONS

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
    "Гипсокартон", "Штукатурка", "Шпаклевка", "Краски", "Клей", "Грунтовка",
    "Гидроизоляция", "Теплоизоляция", "Звукоизоляция", "Пиломатериалы",
    "Фанера", "ДСП", "ОСБ", "Металлопрокат", "Трубы", "Проволока",
    "Крепежные изделия", "Электротовары", "Сантехника", "Отопление",
    "Кровля", "Окна", "Двери", "Напольные покрытия", "Сайдинг", "Вагонка",
    "Ламинат", "Паркет", "Линолеум", "Ковролин"
]

@api_router.get("/material_types/")
def get_material_types():
    return MATERIAL_TYPES

app.include_router(api_router)

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))