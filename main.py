import json
import uvicorn
import databases
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
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

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("Database disconnected.")

# Схемы Pydantic для валидации данных
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None

# Схемы для пользователя
class UserBase(BaseModel):
    username: str
    user_name: str
    email: Optional[str] = None
    user_type: str
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False

class UserIn(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    user_name: Optional[str] = None
    email: Optional[str] = None
    user_type: Optional[str] = None
    specialization: Optional[str] = None
    is_premium: Optional[bool] = None

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

# Схемы для спецтехники
class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    is_premium: bool = False

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

# Проверка пользователя
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

# Регистрация пользователя
@api_router.post("/users/", status_code=status.HTTP_201_CREATED)
async def create_user(user: UserIn):
    query = users.select().where(users.c.username == user.username)
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        username=user.username,
        hashed_password=hashed_password,
        user_name=user.user_name,
        email=user.email,
        user_type=user.user_type,
        specialization=user.specialization
    )
    try:
        last_record_id = await database.execute(query)
        return {"id": last_record_id, **user.dict(exclude={"password"})}
    except exc.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error during user creation. Check if all fields are valid."
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

# Создание заявки на спецтехнику
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
        is_premium=machinery_request.is_premium
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
    "Резчик швов", "Резчик кровли", "Шлифовальная машина", "Бетономешалка", "Растворосмеситель",
    "Пескоструйный аппарат", "Опрессовщик", "Прочистная машина", "Пневмоподатчик", "Штукатурная машина",
    "Окрасочный аппарат", "Компрессорный агрегат", "Гидронасос", "Электроталь",
    "Тепловые пушки", "Дизельные тепловые пушки", "Теплогенераторы", "Осушители воздуха", "Прогрев грунта", "Промышленные вентиляторы",
    "Парогенератор", "Бытовки", "Кран Пионер", "Кран Умелец", "Ручная таль", "Домкраты", "Тележки гидравлические", "Лебедки",
    "Коленчатый подъемник", "Фасадный подъемник", "Телескопический подъемник", "Ножничный подъемник", "Штабелер",
    "Установка алмазного бурения", "Сантехническое оборудование", "Окрасочный аппарат", "Кровельное оборудование",
    "Электромонтажный инструмент", "Резьбонарезной инструмент", "Газорезочное оборудование", "Инструмент для фальцевой кровли",
    "Растворные станции", "Труборезы", "Оборудование для получения лицензии МЧС", "Оборудование для работы с композитом",
    "Рейсмусовый станок", "Дрель на магнитной подошве", "Плиткорезы", "Отрезной станок", "Фрезер", "Камнерезные станки",
    "Экскаваторы", "Погрузчик", "Манипулятор", "Дорожные катки", "Самосвалы", "Автокран", "Автовышка", "Мусоровоз", "Илосос",
    "Канистра", "Монтажный пистолет", "Когти монтерские"
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