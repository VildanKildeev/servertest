# file: main.py
import json
import uvicorn
import databases
import asyncpg
import time
from jose import jws, jwe  # python-jose
import httpx
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, File, UploadFile, Request, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import exc, text, and_
from sqlalchemy.orm import relationship
from sqlalchemy.sql import select, func as sa_func
import os
from dotenv import load_dotenv
from pathlib import Path
import re
from datetime import datetime, date

# --- Database setup ---
# Импортируем все таблицы, включая новые, из файла database.py
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities, database, ratings, work_request_responses, specializations, performer_specializations

load_dotenv()

base_path = Path(__file__).parent
static_path = base_path / "static"

RUSTORE_COMPANY_ID = os.environ.get("RUSTORE_COMPANY_ID")
RUSTORE_SERVICE_KEY = os.environ.get("RUSTORE_SERVICE_KEY")

class RuStorePaymentValidation(BaseModel):
    invoice_id: str  # <-- ВАЖНО: Pay SDK отправляет invoice_id

# Функция генерации токена для RuStore API
def generate_rustore_auth_token():
    """
    Генерирует JWE токен для доступа к API RuStore.
    """
    current_time = int(time.time())
    # Время жизни токена (например, 5 минут)
    exp_time = current_time + 300 
    
    payload = {
        "iss": RUSTORE_KEY_ID,
        "exp": exp_time,
        "iat": current_time,
        "jti": os.urandom(16).hex() # Уникальный ID токена
    }
    
    # Подпись и шифрование (согласно документации RuStore)
    # Внимание: Это упрощенный пример. В зависимости от того, как вы храните ключ,
    # может потребоваться другая обработка (например, если ключ в base64).
    # Обычно используется библиотека python-jose.
    
    # Если у вас возникают сложности с генерацией JWE вручную, 
    # RuStore рекомендует использовать их официальные библиотеки или curl.
    # Для Python самый простой способ - просто передать Service Key в заголовок,
    # если используется Public API (но для v2 платежей часто нужен именно JWE).
    
    # !!! УПРОЩЕННЫЙ ВАРИАНТ ДЛЯ СТАРТА (Если RuStore принимает просто Service Key) !!!
    # Если строгая JWE подпись не проходит, проверьте документацию по "Серверной валидации".
    # Часто достаточно Public-Token.
    
    return "Bearer " + RUSTORE_PRIVATE_KEY # Временная заглушка, см. ниже про JWE

# ПРАВИЛЬНАЯ РЕАЛИЗАЦИЯ JWE ОЧЕНЬ ОБЪЕМНАЯ.
# Для простоты интеграции, используйте этот метод валидации:
async def get_payment_info(invoice_id: str):
    url = f"https://public-api.rustore.ru/public/v2/payments/{invoice_id}"
    
    # Для v2 API нужен токен. 
    # В заголовке 'Public-Token' передаем сервисный ключ (если разрешено)
    # Или генерируем JWE.
    headers = {
        "Public-Token": RUSTORE_SERVICE_KEY, # Попробуйте сначала так
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response

@app.post("/api/validate-rustore-payment")
async def validate_payment(
    payment_data: RuStorePaymentValidation,
    current_user: dict = Depends(get_current_user) # Требуем авторизацию пользователя
):
    """
    Валидация платежа от RuStore Pay SDK (v2)
    """
    invoice_id = payment_data.invoice_id
    print(f"Validating invoice: {invoice_id} for user {current_user['id']}")

    try:
        # 1. Делаем запрос в RuStore API v2
        url = f"https://public-api.rustore.ru/public/v2/payments/{invoice_id}"
        
        # ВАЖНО: Для доступа к этому API нужен валидный токен или Service Key.
        # Проверьте в консоли RuStore права вашего Service Key.
        headers = {
            "Public-Token": RUSTORE_SERVICE_KEY
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            
        if response.status_code != 200:
            print(f"RuStore API Error: {response.text}")
            raise HTTPException(status_code=400, detail="Не удалось проверить платеж в RuStore")

        data = response.json()
        # Пример ответа: {'invoice_id': '...', 'invoice_status': 'CONFIRMED', ...}
        
        status = data.get("invoice_status") # Или просто 'status', проверьте JSON ответа

        # 2. Проверяем статус
        if status == "CONFIRMED" or status == "PAID":
            # 3. Платеж успешен! Начисляем услуги пользователю.
            
            # Пример: Активация премиума
            query = users.update().where(users.c.id == current_user["id"]).values(
                is_premium=True,
                # premium_expires_at=... (добавьте логику даты)
            )
            await database.execute(query)
            
            return {"status": "success", "message": "Оплата подтверждена, услуги начислены."}
        
        elif status == "CREATED" or status == "PROCESSING":
            return {"status": "pending", "message": "Платеж в обработке."}
        else:
            return {"status": "error", "message": f"Статус платежа: {status}"}

    except Exception as e:
        print(f"Validation Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка сервера при валидации")

# V-- ДОБАВЬТЕ ЭТИ 3 СТРОКИ --V
SECRET_KEY = os.environ.get("SECRET_KEY", "c723f5b8a5aff5f8f596f265f833503d25e36f3c178a48b32c6913c3e601c0d4")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120 # Время жизни токена в минутах

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")

app = FastAPI(title="СМЗ.РФ API")
api_router = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=static_path), name="static")

# --- Startup / Shutdown события ---
@app.on_event("startup")
async def startup():
    await database.connect()
    metadata.create_all(engine)
    print("Database connected.")

    # Заполняем справочник специализаций, если он пуст
    if not await database.fetch_one(specializations.select().limit(1)):
        print("Specializations not found, adding default list...")
        default_specs = [
            {"code": "electrician", "name": "Электрик"}, {"code": "plumber", "name": "Сантехник"},
{"code": "carpenter", "name": "Плотник"}, {"code": "handyman", "name": "Мастер на час"},
{"code": "finisher", "name": "Отделочник"}, {"code": "welder", "name": "Сварщик"},
{"code": "mover", "name": "Грузчик"},
{"code": "earthworks", "name": "Земляные работы"}, {"code": "foundations", "name": "Фундаменты и основания"},
{"code": "masonry", "name": "Кладочные работы"}, {"code": "metal_structures", "name": "Металлоконструкции"},
{"code": "roofing", "name": "Кровельные работы"}, {"code": "glazing_facades", "name": "Остекление и фасадные работы"},
{"code": "internal_engineering_networks", "name": "Внутренние инженерные сети"}, {"code": "heating_heat_supply", "name": "Отопление и теплоснабжение"},
{"code": "ventilation_aircon", "name": "Вентиляция и кондиционирование"}, {"code": "ceilings_installation", "name": "Монтаж потолков"},
{"code": "semi_dry_screed", "name": "Полусухая стяжка пола"}, {"code": "painting", "name": "Малярные работы"},
{"code": "landscaping", "name": "Благоустройство территории"}, {"code": "turnkey_house_building", "name": "Строительство домов под ключ"},
{"code": "demolition", "name": "Демонтажные работы"}, {"code": "equipment_installation", "name": "Монтаж оборудования"},
{"code": "laborers", "name": "Разнорабочие"}, {"code": "cleaning", "name": "Клининг, уборка помещений"},
{"code": "drilling_wells", "name": "Бурение, устройство скважин"}, {"code": "design", "name": "Проектирование"},
{"code": "geology", "name": "Геология"},
        ]
        await database.execute_many(specializations.insert(), default_specs)
        print("Specializations added.")

    # Код для начального заполнения городов (оставлен без изменений)
    if not await database.fetch_one(cities.select().limit(1)):
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
    {"name": "Уфа"},
    {"name": "Красноярск"},
    {"name": "Пермь"},
    {"name": "Воронеж"},
    {"name": "Волгоград"},
    {"name": "Краснодар"},
]
        await database.execute(cities.insert().values(default_cities))
        print("Города успешно добавлены.")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("Database disconnected.")

# --- Схемы Pydantic (модели данных) ---

# --- НОВЫЕ И ОБНОВЛЕННЫЕ МОДЕЛИ ---
class Specialization(BaseModel):
    code: str
    name: str

class PerformerSpecializationOut(Specialization):
    is_primary: bool

class UserSpecializationsUpdate(BaseModel):
    specialization_codes: List[str]
    primary_code: Optional[str] = None # Сделаем необязательным, так как будем его игнорировать

class AdditionalSpecializationUpdate(BaseModel):
    """Модель для обновления только дополнительных специализаций."""
    additional_codes: List[str] = Field(..., description="Список кодов дополнительных специализаций")

class RuStoreVerificationRequest(BaseModel):
    invoiceId: str # Получаем ID счета от приложения

class SubscriptionStatus(BaseModel):
    is_premium: bool
    premium_until: Optional[datetime] = None

class CheckoutSession(BaseModel):
    checkout_url: Optional[str] = None
    activated: Optional[bool] = None

class UserOut(BaseModel):
    id: int
    email: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None # Для обратной совместимости
    is_premium: bool
    premium_until: Optional[datetime] = None # Новое поле
    average_rating: float
    ratings_count: int
    # Новое поле со списком всех специализаций
    specializations: List[PerformerSpecializationOut] = []

    class Config:
        from_attributes = True

# --- Старые модели (без изменений, кроме добавления в UserOut) ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    phone_number: str
    user_type: str = Field(..., description="Тип пользователя: ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ")
    specialization: Optional[str] = None # При регистрации это будет primary

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class WorkRequestIn(BaseModel):
    description: str
    specialization: str
    budget: float
    contact_info: str
    city_id: int
    is_premium: bool = False
    is_master_visit_required: bool = False

class ResponseCreate(BaseModel):
    comment: Optional[str] = None

class ResponseOut(UserOut):
    response_id: int
    response_comment: Optional[str] = None
    response_created_at: datetime

class RatingIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    rating_type: str # 'TO_EXECUTOR' или 'TO_CUSTOMER'

class City(BaseModel):
    id: int
    name: str
    class Config: from_attributes = True

# ... (Остальные модели In/Ad без изменений)
class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: str
    rental_price: float
    contact_info: str
    city_id: int
    is_premium: bool = False
    rental_date: date
    min_rental_hours: int = Field(..., ge=1)
    has_delivery: bool = False
    delivery_address: Optional[str] = None

class ToolRequestIn(BaseModel):
    tool_name: str
    description: str
    rental_price: float
    contact_info: str
    city_id: int
    count: int = Field(..., ge=1)
    rental_start_date: date
    rental_end_date: date
    has_delivery: bool = False
    delivery_address: Optional[str] = None

class MaterialAdIn(BaseModel):
    material_type: str
    description: str
    price: float
    contact_info: str
    city_id: int
    is_premium: bool = False

class StatusUpdate(BaseModel):
    status: str

# --- Утилиты ---

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def authenticate_user(username: str, password: str):
    user_db = await database.fetch_one(users.select().where(users.c.email == username))
    if not user_db or not verify_password(password, user_db["hashed_password"]):
        return None
    return user_db

def is_user_premium(user: dict) -> bool:
    """Проверяет, активен ли премиум-статус у пользователя."""
    if not user:
        return False

    is_active = user.get("is_premium", False)
    premium_until = user.get("premium_until")

    if not is_active or not premium_until:
        return False

    # --- ИСПРАВЛЕННАЯ ЛОГИКА ---
    # 1. Получаем текущую дату (без времени)
    today = date.today()

    # 2. Преобразуем premium_until в объект date, если это datetime
    premium_until_date = premium_until
    if isinstance(premium_until, datetime):
        premium_until_date = premium_until.date()

    # 3. Теперь сравнение безопасно, так как мы сравниваем date с date.
    # Если подписка истекла (т.е. дата окончания стала меньше сегодняшней),
    # то премиум неактивен.
    if premium_until_date < today:
        # TODO: Здесь можно добавить фоновую задачу для снятия флага is_premium в базе.
        return False

    return True

def mask_contact(contact_info: str) -> str:
    """Маскирует контактную информацию."""
    if not contact_info:
        return ""
    # Маскируем email
    masked = re.sub(r'(\S{1,2})(\S+)(@)(\S+)(\.\S+)', r'\1***\3***\5', contact_info)
    # Маскируем телефон
    masked = re.sub(r'\+?\d{1,2}\s?\(?(\d{3})\)?\s?(\d{3})[-\s]?(\d{2})[-\s]?(\d{2})', r'+7 (***) ***-**-\4', masked)
    return masked

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось проверить учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user_db = await database.fetch_one(users.select().where(users.c.email == email))
    if user_db is None:
        raise credentials_exception

    # Преобразуем в словарь, чтобы добавить вычисляемое поле
    user_dict = dict(user_db)
    # Добавляем актуальный премиум статус
    user_dict['is_premium'] = is_user_premium(user_dict)

    return user_dict

# --- Маршруты API ---

@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_index(): return FileResponse(static_path / "index.html")

@app.get("/privacy", response_class=FileResponse, include_in_schema=False)
async def serve_privacy_policy():
    """
    Отдает страницу 'Политика конфиденциальности'.
    """
    return FileResponse(static_path / "privacy_policy.html")

@app.get("/terms", response_class=FileResponse, include_in_schema=False)
async def serve_user_agreement():
    """
    Отдает страницу 'Пользовательское соглашение'.
    """
    return FileResponse(static_path / "user_agreement.html")

# --- Регистрация, логин, профиль ---

@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user_db = await authenticate_user(form_data.username, form_data.password)
    if not user_db:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    access_token = create_access_token({"sub": user_db["email"]}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def create_user(user: UserCreate):
    if await database.fetch_one(users.select().where(users.c.email == user.email)):
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует.")
    if user.user_type == "ИСПОЛНИТЕЛЬ" and not user.specialization:
        raise HTTPException(status_code=400, detail="Для 'ИСПОЛНИТЕЛЯ' специализация обязательна.")

    async with database.transaction():
        hashed_password = get_password_hash(user.password)
        query = users.insert().values(
            email=user.email, hashed_password=hashed_password, phone_number=user.phone_number,
            user_type=user.user_type, specialization=user.specialization, is_premium=False,
            average_rating=0.0, ratings_count=0
        )
        user_id = await database.execute(query)

        # Если это исполнитель, добавляем его стартовую специализацию как основную

        if user.user_type == "ИСПОЛНИТЕЛЬ":
            spec_query = select(specializations.c.code).where(specializations.c.name == user.specialization)
            spec_code = await database.fetch_val(spec_query)
            if spec_code:
                ps_query = performer_specializations.insert().values(
                    user_id=user_id, specialization_code=spec_code, is_primary=True
                )
                await database.execute(ps_query)

    created_user_raw = await database.fetch_one(users.select().where(users.c.id == user_id))
    # Собираем UserOut
    response_data = dict(created_user_raw)
    response_data["average_rating"] = response_data.get("average_rating") or 0.0
    response_data["ratings_count"] = response_data.get("ratings_count") or 0
    response_data["is_premium"] = is_user_premium(response_data)
    response_data["specializations"] = []

    if response_data['user_type'] == 'ИСПОЛНИТЕЛЬ':
         # Получаем созданную специализацию
        join = performer_specializations.join(specializations, performer_specializations.c.specialization_code == specializations.c.code)
        query = select(specializations.c.code, specializations.c.name, performer_specializations.c.is_primary).select_from(join).where(performer_specializations.c.user_id == user_id)
        user_specs = await database.fetch_all(query)
        response_data["specializations"] = [dict(s) for s in user_specs]

    return response_data

@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']

    # Добавляем специализации, если пользователь - исполнитель
    current_user['specializations'] = []
    if current_user['user_type'] == 'ИСПОЛНИТЕЛЬ':
        join = performer_specializations.join(specializations, performer_specializations.c.specialization_code == specializations.c.code)
        query = select(specializations.c.code, specializations.c.name, performer_specializations.c.is_primary).select_from(join).where(performer_specializations.c.user_id == user_id)
        user_specs = await database.fetch_all(query)
        current_user['specializations'] = [dict(s) for s in user_specs]

    # Устанавливаем значения по умолчанию для старых записей
    current_user["average_rating"] = current_user.get("average_rating") or 0.0
    current_user["ratings_count"] = current_user.get("ratings_count") or 0
    return current_user

# --- Основная логика заявок на работу (СИЛЬНО ИЗМЕНЕНА) ---

@api_router.post("/work_requests/", status_code=status.HTTP_201_CREATED)
async def create_work_request(work_request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    request_data = work_request.model_dump()
    request_data["status"] = "ОЖИДАЕТ"
    query = work_requests.insert().values(user_id=current_user["id"], **request_data)
    request_id = await database.execute(query)
    return {"id": request_id, "status": "ОЖИДАЕТ", **work_request.model_dump()}

@api_router.get("/work_requests/")
async def get_work_requests(city_id: int, current_user: dict = Depends(get_current_user)):
    # ПРАВИЛО 1: Заказчикам запрещен доступ
    if current_user["user_type"] == "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только исполнители могут просматривать общую ленту заявок.")

    # --- ИСПРАВЛЕННАЯ ЛОГИКА ---

    # 1. Получаем все специализации исполнителя (и основную, и дополнительные)
    join = performer_specializations.join(specializations, performer_specializations.c.specialization_code == specializations.c.code)
    specs_query = select(specializations.c.name, performer_specializations.c.is_primary).select_from(join).where(performer_specializations.c.user_id == current_user["id"])
    user_specs_records = await database.fetch_all(specs_query)

    if not user_specs_records:
        return [] # Если у исполнителя нет специализаций, он ничего не увидит

    # 2. Составляем список всех его специализаций и отдельно запоминаем основную
    all_user_spec_names = [s['name'] for s in user_specs_records]
    primary_spec_name = next((s['name'] for s in user_specs_records if s['is_primary']), None)

    responded_requests_query = select(work_request_responses.c.work_request_id).where(
        work_request_responses.c.executor_id == current_user["id"]
    )
    responded_request_ids = {row['work_request_id'] for row in await database.fetch_all(responded_requests_query)}

    # 4. Делаем ОДИН запрос в базу, чтобы получить ВСЕ заявки по ВСЕМ специализациям,
    #    ИСКЛЮЧАЯ те, на которые уже был отклик.
    query = work_requests.select().where(
        work_requests.c.city_id == city_id,
        work_requests.c.status == "ОЖИДАЕТ",
        work_requests.c.user_id != current_user["id"],
        work_requests.c.specialization.in_(all_user_spec_names),
        work_requests.c.id.notin_(responded_request_ids)  # <-- ДОБАВЛЕН ЭТОТ ФИЛЬТР
    ).order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc())
    
    all_requests = await database.fetch_all(query)

    # 4. Теперь обрабатываем результаты в зависимости от статуса премиум
    user_is_premium = is_user_premium(current_user)
    
    if user_is_premium:
        # Премиум-пользователь видит всё как есть.
        return all_requests

    # 5. Для обычного пользователя применяем маскировку выборочно
    processed_requests = []
    for request in all_requests:
        request_dict = dict(request) # Преобразуем в изменяемый словарь

        # Если специализация заявки НЕ является основной для пользователя
        if request_dict["specialization"] != primary_spec_name:
            # Маскируем контакты и добавляем флаг для фронтенда
            request_dict["contact_info"] = mask_contact(request_dict["contact_info"])
            request_dict["is_masked_for_user"] = True # <-- Новый флаг для фронтенда
        else:
            # Это заявка по основной специализации, ничего не маскируем
            request_dict["is_masked_for_user"] = False

        processed_requests.append(request_dict)

    return processed_requests

@api_router.post("/work_requests/{request_id}/respond", status_code=201)
async def respond_to_work_request(request_id: int, response: ResponseCreate, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только исполнители могут откликаться.")

    work_req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not work_req or work_req["status"] != "ОЖИДАЕТ":
        raise HTTPException(status_code=400, detail="Нельзя откликнуться на эту заявку (она неактивна).")

    # ПРОВЕРКА ПРАВ НА ОТКЛИК
    user_is_premium = is_user_premium(current_user)
    join = performer_specializations.join(specializations, performer_specializations.c.specialization_code == specializations.c.code)
    specs_query = select(specializations.c.name, performer_specializations.c.is_primary).select_from(join).where(performer_specializations.c.user_id == current_user["id"])
    user_specs_records = await database.fetch_all(specs_query)

    allowed_specs = [s['name'] for s in user_specs_records]
    if not user_is_premium:
        primary_spec_name = next((s['name'] for s in user_specs_records if s['is_primary']), None)
        allowed_specs = [primary_spec_name] if primary_spec_name else []

    if work_req['specialization'] not in allowed_specs:
         raise HTTPException(status_code=403, detail="Вы не можете откликнуться на заявку с этой специализацией.")

    try:
        await database.execute(work_request_responses.insert().values(
            work_request_id=request_id, executor_id=current_user["id"], comment=response.comment
        ))
    except exc.IntegrityError:
        raise HTTPException(status_code=400, detail="Вы уже откликались на эту заявку.")

    return {"message": "Вы успешно откликнулись на заявку."}

# --- НОВЫЕ ЭНДПОИНТЫ ДЛЯ СПЕЦИАЛИЗАЦИЙ И ПОДПИСКИ ---

@api_router.get("/me/specializations", response_model=List[PerformerSpecializationOut])
async def get_my_specializations(current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        return []

    join = performer_specializations.join(specializations, performer_specializations.c.specialization_code == specializations.c.code)
    query = select(specializations.c.code, specializations.c.name, performer_specializations.c.is_primary).select_from(join).where(performer_specializations.c.user_id == current_user["id"])
    return await database.fetch_all(query)

# # УДАЛЕНО: Этот эндпоинт был дублирующим и не использовался фронтендом.
# # Логика перенесена в PATCH-эндпоинт ниже.
# @api_router.post("/me/specializations", status_code=200)
# async def update_me_specializations(data: UserSpecializationsUpdate, current_user: dict = Depends(get_current_user)):
#     # ... (старый код удален) ...

@api_router.get("/me/subscription", response_model=SubscriptionStatus)
async def get_my_subscription(current_user: dict = Depends(get_current_user)):
    return {
        "is_premium": is_user_premium(current_user),
        "premium_until": current_user.get("premium_until")
    }

@api_router.post("/verify/rustore", response_model=SubscriptionStatus)
async def verify_rustore_purchase(
    data: RuStoreVerificationRequest, 
    current_user: dict = Depends(get_current_user)
):
    """
    Проверяет чек (invoiceId) на стороне сервера RuStore.
    """
    
    # 1. Проверяем, что ключи для RuStore API настроены на сервере
    if not RUSTORE_COMPANY_ID or not RUSTORE_SERVICE_KEY:
        print("Ошибка: Переменные RUSTORE_COMPANY_ID или RUSTORE_SERVICE_KEY не установлены.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Сервис оплаты временно недоступен."
        )

    # 2. Формируем URL для API RuStore
    # (Вам нужно уточнить URL в документации RuStore API для проверки чека)
# Используем v2 API, который соответствует Pay SDK
RUSTORE_VERIFY_URL = f"https://public-api.rustore.ru/public/v2/payments/{data.invoiceId}"
    
headers = {
    "Public-Token": RUSTORE_SERVICE_KEY 
    # "Authorization" здесь не нужен для этого конкретного метода v2, если используете сервисный ключ как Public-Token
}

    try:
        # 3. Делаем асинхронный запрос к RuStore
        async with httpx.AsyncClient() as client:
            response = await client.get(RUSTORE_VERIFY_URL, headers=headers)
        
        # 4. Анализируем ответ
        if response.status_code == 404:
            raise HTTPException(status_code=400, detail="Платеж не найден (404).")
        
        # Пробрасываем другие ошибки
        response.raise_for_status() 
        
        payment_data = response.json()
        
        # 5. ВАЖНАЯ ПРОВЕРКА: Убеждаемся, что статус "PAID" или "CONFIRMED"
        # (Используйте точный статус из документации RuStore)
        payment_status = payment_data.get("body", {}).get("invoiceStatus")
        
        if payment_status not in ["PAID", "CONFIRMED"]: # Уточните эти статусы
             raise HTTPException(
                status_code=400, 
                detail=f"Платеж не подтвержден. Статус: {payment_status}"
            )

        # TODO: Дополнительная проверка. 
        # Убедитесь, что `productId` в `payment_data`
        # соответствует 'premium_30_days' и что сумма верная.

    except httpx.HTTPStatusError as e:
        print(f"Ошибка HTTP при проверке RuStore: {e.response.text}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка при обращении к сервису оплаты: {e.response.status_code}"
        )
    except Exception as e:
        print(f"Неизвестная ошибка при проверке RuStore: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Внутренняя ошибка сервиса оплаты."
        )

    # 6. Все в порядке! Платеж подтвержден. Активируем премиум.
    premium_until_date = datetime.utcnow() + timedelta(days=30)
    
    query = users.update().where(users.c.id == current_user["id"]).values(
        is_premium=True,
        premium_until=premium_until_date
    )
    await database.execute(query)
    
    print(f"RuStore: Премиум успешно активирован для пользователя {current_user['id']}")

    return {
        "is_premium": True,
        "premium_until": premium_until_date
    }

# --- Справочники ---
@api_router.get("/cities/", response_model=List[City])
async def get_cities():
    return await database.fetch_all(cities.select().order_by(cities.c.name))

@api_router.get("/specializations/", response_model=List[Specialization])
async def get_specializations_list():
    query = specializations.select().order_by(specializations.c.name)
    return await database.fetch_all(query)

# ... (Остальные справочники без изменений)
@api_router.get("/machinery_types/")
async def get_machinery_types():
    return [
  {
    "group": "🟡 1. ЭКСКАВАТОРЫ",
    "items": [
      { "id": 6,  "name": "ЭКСКАВАТОР: Гусеничные" },
      { "id": 7,  "name": "ЭКСКАВАТОР: Колёсные" },
      { "id": 8,  "name": "ЭКСКАВАТОР: Мини-экскаваторы" },
      { "id": 9,  "name": "ЭКСКАВАТОР: Планировщики" },
      { "id": 10, "name": "ЭКСКАВАТОР: Длиннорукие (Long Reach)" },
      { "id": 11, "name": "ЭКСКАВАТОР: С гидромолотом, ямобуром, вибропогружателем" }
    ]
  },
  {
    "group": "🟡 2. ПОГРУЗЧИКИ",
    "items": [
      { "id": 12, "name": "ПОГРУЗЧИК: Фронтальные погрузчики" },
      { "id": 13, "name": "ПОГРУЗЧИК: Мини-погрузчики (Bobcat и аналоги)" },
      { "id": 14, "name": "ПОГРУЗЧИК: Телескопические погрузчики" },
      { "id": 15, "name": "ПОГРУЗЧИК: Вилочные погрузчики (дизель, газ, электрические)" }
    ]
  },
  {
    "group": "🟡 3. АВТОКРАНЫ И МАНИПУЛЯТОРЫ",
    "items": [
      { "id": 16, "name": "КРАН: Автокраны (16–100 тонн)" },
      { "id": 17, "name": "КРАН: Краны-манипуляторы" },
      { "id": 18, "name": "КРАН: Гусеничные краны" },
      { "id": 19, "name": "КРАН: Башенные краны (сборка/демонтаж)" }
    ]
  },
  {
    "group": "🟡 4. САМОСВАЛЫ И СПЕЦТРАНСПОРТ",
    "items": [
      { "id": 20, "name": "САМОСВАЛ: Самосвалы 10–30 т" },
      { "id": 21, "name": "САМОСВАЛ: Тонар, Шакман, КамАЗ, Scania, MAN и др." },
      { "id": 22, "name": "САМОСВАЛ: Бортовые машины" },
      { "id": 23, "name": "САМОСВАЛ: Низкорамные тралы" },
      { "id": 24, "name": "САМОСВАЛ: Вахтовки, автобусы, спецавтомобили" }
    ]
  },
  {
    "group": "🟡 5. АВТОВЫШКИ И ПОДЪЁМНИКИ",
    "items": [
      { "id": 25, "name": "АВТОВЫШКА: Автовышки (10–45 м)" },
      { "id": 26, "name": "ПОДЪЁМНИК: Ножничные подъёмники" },
      { "id": 27, "name": "ПОДЪЁМНИК: Коленчатые подъёмники" },
      { "id": 28, "name": "ПОДЪЁМНИК: Мачтовые и телескопические платформы" }
    ]
  },
  {
    "group": "🟡 6. ДОРОЖНАЯ ТЕХНИКА",
    "items": [
      { "id": 29, "name": "ДОРОЖНАЯ ТЕХНИКА: Катки (вибрационные, комбинированные)" },
      { "id": 30, "name": "ДОРОЖНАЯ ТЕХНИКА: Асфальтоукладчики" },
      { "id": 31, "name": "ДОРОЖНАЯ ТЕХНИКА: Грейдеры" },
      { "id": 32, "name": "ДОРОЖНАЯ ТЕХНИКА: Фрезы дорожные" },
      { "id": 33, "name": "ДОРОЖНАЯ ТЕХНИКА: Гудронаторы" }
    ]
  },
  {
    "group": "🟡 7. БЕТОН И СМЕСИТЕЛИ",
    "items": [
      { "id": 34, "name": "БЕТОН: Бетононасосы (стационарные и автобетононасосы)" },
      { "id": 35, "name": "БЕТОН: Бетоносмесители" },
      { "id": 36, "name": "БЕТОН: Растворонасосы" },
      { "id": 37, "name": "БЕТОН: Миксеры" }
    ]
  },
  {
    "group": "🟡 8. УТИЛИТЫ И ДОП. ОБОРУДОВАНИЕ",
    "items": [
      { "id": 38, "name": "УТИЛИТА: Виброплиты, трамбовки" },
      { "id": 39, "name": "УТИЛИТА: Компрессоры" },
      { "id": 40, "name": "УТИЛИТА: Генераторы (дизельные/бензиновые)" },
      { "id": 41, "name": "УТИЛИТА: Сварочные агрегаты" },
      { "id": 42, "name": "УТИЛИТА: Штукатурные станции" }
    ]
  },
  {
    "group": "🟡 9. КОММУНАЛЬНАЯ ТЕХНИКА",
    "items": [
      { "id": 43, "name": "КОММУНАЛЬНАЯ: Водовозы" },
      { "id": 44, "name": "КОММУНАЛЬНАЯ: Илососы, каналопромывочные машины" },
      { "id": 45, "name": "КОММУНАЛЬНАЯ: Поливомоечные" },
      { "id": 46, "name": "КОММУНАЛЬНАЯ: Снегоуборочные" }
    ]
  },
  {
    "group": "🟡 10. БУРОВАЯ И СПЕЦИАЛЬНАЯ ТЕХНИКА",
    "items": [
      { "id": 47, "name": "БУРОВАЯ: Ямобуры" },
      { "id": 48, "name": "БУРОВАЯ: Гидробуры" },
      { "id": 49, "name": "БУРОВАЯ: Буровые установки (скважины, сваи)" },
      { "id": 50, "name": "БУРОВАЯ: Вибропогружатели" },
      { "id": 51, "name": "БУРОВАЯ: Машины для забивки свай" }
    ]
  }
]


@api_router.get("/tool_names/")
async def get_tool_names():
    return [
  {"id": 6, "name": "Виброплиты"},
  {"id": 7, "name": "Вибротрамбовки"},
  {"id": 8, "name": "Резчики швов"},
  {"id": 9, "name": "Бензорезы"},
  {"id": 10, "name": "Воздуходувка"},
  {"id": 11, "name": "Виброкатки"},
  {"id": 12, "name": "Осветительные мачты"},
  {"id": 13, "name": "Бензиновые отбойные молотки"},
  {"id": 14, "name": "Дизельные генераторы"},
  {"id": 15, "name": "Бензиновые генераторы"},
  {"id": 16, "name": "Отбойные молотки"},
  {"id": 17, "name": "Перфораторы"},
  {"id": 18, "name": "Штроборезы"},
  {"id": 19, "name": "Торцовочные пилы"},
  {"id": 20, "name": "Монтажные пилы"},
  {"id": 21, "name": "Циркулярные пилы"},
  {"id": 22, "name": "Сабельные пилы"},
  {"id": 23, "name": "УШМ"},
  {"id": 24, "name": "Краскопульты"},
  {"id": 25, "name": "Электрорубанки"},
  {"id": 26, "name": "Электролобзики"},
  {"id": 27, "name": "Шуруповерты"},
  {"id": 28, "name": "Электропилы"},
  {"id": 29, "name": "Гайковерты"},
  {"id": 30, "name": "Строительные фены"},
  {"id": 31, "name": "Ножницы по металлу"},
  {"id": 32, "name": "Дрели электрические"},
  {"id": 33, "name": "Заклепочники"},
  {"id": 34, "name": "Реноватор"},
  {"id": 35, "name": "Бензобур"},
  {"id": 36, "name": "Триммер"},
  {"id": 37, "name": "Бензопила"},
  {"id": 38, "name": "Культиваторы и мотоблоки"},
  {"id": 39, "name": "Газонокосилка"},
  {"id": 40, "name": "Каток садовый"},
  {"id": 41, "name": "Вертикуттер"},
  {"id": 42, "name": "Аэратор"},
  {"id": 43, "name": "Кусторез"},
  {"id": 44, "name": "Измельчитель веток"},
  {"id": 45, "name": "Дровокол"},
  {"id": 46, "name": "Снегоуборочная машина"},
  {"id": 47, "name": "Садовый пылесос - воздуходувка"},
  {"id": 48, "name": "Садовая тележка"},
  {"id": 49, "name": "Бензиновый опрыскиватель"},
  {"id": 50, "name": "Виброрейка"},
  {"id": 51, "name": "Бетономешалка"},
  {"id": 52, "name": "Глубинный вибратор"},
  {"id": 53, "name": "Миксер"},
  {"id": 54, "name": "Оборудование для обогрева бетона"},
  {"id": 55, "name": "Растворные емкости"},
  {"id": 56, "name": "Инструмент для вязки арматуры"},
  {"id": 57, "name": "Станок для резки арматуры"},
  {"id": 58, "name": "Станки для гибки арматуры (Армогибы)"},
  {"id": 59, "name": "Монолитные стойки"},
  {"id": 60, "name": "Строительные леса"},
  {"id": 61, "name": "Вышки тура"},
  {"id": 62, "name": "Лестницы и стремянки"},
  {"id": 63, "name": "Опалубка"},
  {"id": 64, "name": "Сетка для строительных лесов"},
  {"id": 65, "name": "Рукав для мусора"},
  {"id": 66, "name": "Мозаично-шлифовальные машины"},
  {"id": 67, "name": "Паркето-шлифовальные машины"},
  {"id": 68, "name": "Затирочные машины по бетону"},
  {"id": 69, "name": "Эксцентриковые шлифовальные машины"},
  {"id": 70, "name": "Ленточно-шлифовальные машины"},
  {"id": 71, "name": "Шлифовальные машины для стен"},
  {"id": 72, "name": "Фрезеровальные машины по бетону"},
  {"id": 73, "name": "Строгальные машины"},
  {"id": 74, "name": "Дизельные компрессоры"},
  {"id": 75, "name": "Электрические компрессоры"},
  {"id": 76, "name": "Мотопомпы"},
  {"id": 77, "name": "Погружные насосы"},
  {"id": 78, "name": "Пароочиститель"},
  {"id": 79, "name": "Промышленный пылесос"},
  {"id": 80, "name": "Минимойка"},
  {"id": 81, "name": "Роботы для уборки"},
  {"id": 82, "name": "Поломоечная машина"},
  {"id": 83, "name": "Сварочный аппарат"},
  {"id": 84, "name": "Паяльник для полипропиленовых труб"},
  {"id": 85, "name": "Паяльник для линолеума"},
  {"id": 86, "name": "Аппарат для стыковки труб большого диаметра"},
  {"id": 87, "name": "Детектор проводки"},
  {"id": 88, "name": "Оптический нивелир"},
  {"id": 89, "name": "Лазерный нивелир"},
  {"id": 90, "name": "Лазерный уровень"},
  {"id": 91, "name": "Толщиномер для бетона"},
  {"id": 92, "name": "Дальномер"},
  {"id": 93, "name": "Тепловизор"},
  {"id": 94, "name": "Металлоискатель"},
  {"id": 95, "name": "Склерометр"},
  {"id": 96, "name": "Толщиномер лако-красочного покрытия"},
  {"id": 97, "name": "Люксометр"},
  {"id": 98, "name": "Влагомер"},
  {"id": 99, "name": "Пирометр"},
  {"id": 100, "name": "ТДС метр - солемер"},
  {"id": 101, "name": "Дозиметр"},
  {"id": 102, "name": "Тестер емкости АКБ"},
  {"id": 103, "name": "Толщиномер для металла"},
  {"id": 104, "name": "Мегаомметр"},
  {"id": 105, "name": "Электрические тепловые пушки"},
  {"id": 106, "name": "Газовые тепловые пушки"},
  {"id": 107, "name": "Дизельные тепловые пушки"},
  {"id": 108, "name": "Теплогенераторы"},
  {"id": 109, "name": "Осушители воздуха"},
  {"id": 110, "name": "Прогрев грунта"},
  {"id": 111, "name": "Промышленные вентиляторы"},
  {"id": 112, "name": "Парогенератор"},
  {"id": 113, "name": "Бытовки"},
  {"id": 114, "name": "Кран Пионер"},
  {"id": 115, "name": "Кран Умелец"},
  {"id": 116, "name": "Ручная таль"},
  {"id": 117, "name": "Домкраты"},
  {"id": 118, "name": "Тележки гидравлические"},
  {"id": 119, "name": "Лебедки"},
  {"id": 120, "name": "Коленчатый подъемник"},
  {"id": 121, "name": "Фасадный подъемник"},
  {"id": 122, "name": "Телескопический подъемник"},
  {"id": 123, "name": "Ножничный подъемник"},
  {"id": 124, "name": "Штабелер"},
  {"id": 125, "name": "Установка алмазного бурения"},
  {"id": 126, "name": "Сантехническое оборудование"},
  {"id": 127, "name": "Окрасочный аппарат"},
  {"id": 128, "name": "Кровельное оборудование"},
  {"id": 129, "name": "Электромонтажный инструмент"},
  {"id": 130, "name": "Резьбонарезной инструмент"},
  {"id": 131, "name": "Газорезочное оборудование"},
  {"id": 132, "name": "Инструмент для фальцевой кровли"},
  {"id": 133, "name": "Растворные станции"},
  {"id": 134, "name": "Труборезы"},
  {"id": 135, "name": "Оборудование для получения лицензии МЧС"},
  {"id": 136, "name": "Оборудование для работы с композитом"},
  {"id": 137, "name": "Рейсмусовый станок"},
  {"id": 138, "name": "Дрель на магнитной подошве"},
  {"id": 139, "name": "Плиткорезы"},
  {"id": 140, "name": "Отрезной станок"},
  {"id": 141, "name": "Фрезер"},
  {"id": 142, "name": "Камнерезные станки"},
  {"id": 143, "name": "Экскаваторы"},
  {"id": 144, "name": "Погрузчик"},
  {"id": 145, "name": "Манипулятор"},
  {"id": 146, "name": "Дорожные катки"},
  {"id": 147, "name": "Самосвалы"},
  {"id": 148, "name": "Автокран"},
  {"id": 149, "name": "Автовышка"},
  {"id": 150, "name": "Мусоровоз"},
  {"id": 151, "name": "Илосос"},
  {"id": 152, "name": "Канистра"},
  {"id": 153, "name": "Монтажный пистолет"},
  {"id": 154, "name": "Когти монтерские"},
  {"id": 155, "name": "Прицепы"},
  {"id": 156, "name": "Удлинители"},
  {"id": 157, "name": "Трубогибы"},
  {"id": 158, "name": "Стабилизатор напряжения"},
  {"id": 159, "name": "Стеклодомкраты"},
  {"id": 160, "name": "Динамометрический ключ"},
  {"id": 161, "name": "Ручной инструмент"},
  {"id": 162, "name": "Полезное"},
  {"id": 163, "name": "Зарядные устройства"},
]


@api_router.get("/material_types/")
async def get_material_types():
    return [
        {"id": 1, "name": "Кирпич"}, {"id": 2, "name": "Цемент"},
        {"id": 3, "name": "Песок"}, {"id": 4, "name": "Щебень"},
        {"id": 5, "name": "Пиломатериалы"},
    ]

# --- Старые эндпоинты, которые остаются без изменений в логике ---
# (Копипаст из исходного файла для полноты)

@api_router.get("/users/me/requests/")
async def get_my_requests(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    if current_user["user_type"] == "ЗАКАЗЧИК":
        query = work_requests.select().where(work_requests.c.user_id == user_id)
    elif current_user["user_type"] == "ИСПОЛНИТЕЛЬ":
        assigned_q = select(work_requests.c.id).where(work_requests.c.executor_id == user_id)
        responded_q = select(work_request_responses.c.work_request_id).where(work_request_responses.c.executor_id == user_id)
        all_my_request_ids = assigned_q.union(responded_q)
        query = work_requests.select().where(work_requests.c.id.in_(all_my_request_ids))
    else: return []

    requests_db = await database.fetch_all(query.order_by(work_requests.c.created_at.desc()))
    response_requests = []
    for req in requests_db:
        req_dict = dict(req)
        req_dict['has_rated'] = False
        if req_dict['status'] == 'ВЫПОЛНЕНА':
            rating_exists_query = ratings.select().where((ratings.c.work_request_id == req_dict['id']) & (ratings.c.rater_user_id == user_id))
            if await database.fetch_one(rating_exists_query):
                req_dict['has_rated'] = True
        response_requests.append(req_dict)
    return response_requests

@api_router.get("/work_requests/{request_id}/responses", response_model=List[ResponseOut])
async def get_work_request_responses(request_id: int, current_user: dict = Depends(get_current_user)):
    work_req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not work_req or work_req["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Это не ваша заявка.")
    query = work_request_responses.join(users, work_request_responses.c.executor_id == users.c.id).select().with_only_columns(
        users.c.id, users.c.email, users.c.phone_number, users.c.user_type, users.c.specialization,
        users.c.is_premium,
        sa_func.coalesce(users.c.average_rating, 0.0).label("average_rating"),
        sa_func.coalesce(users.c.ratings_count, 0).label("ratings_count"),
        work_request_responses.c.id.label("response_id"),
        work_request_responses.c.comment.label("response_comment"),
        work_request_responses.c.created_at.label("response_created_at")
    ).where(work_request_responses.c.work_request_id == request_id)
    return await database.fetch_all(query)

@api_router.patch("/work_requests/{request_id}/responses/{response_id}/approve")
async def approve_work_request_response(request_id: int, response_id: int, current_user: dict = Depends(get_current_user)):
    async with database.transaction():
        work_req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
        if not work_req or work_req["user_id"] != current_user["id"] or work_req["status"] != "ОЖИДАЕТ":
            raise HTTPException(status_code=403, detail="Невозможно назначить исполнителя для этой заявки.")
        response = await database.fetch_one(work_request_responses.select().where(work_request_responses.c.id == response_id))
        if not response or response["work_request_id"] != request_id: raise HTTPException(status_code=404, detail="Отклик не найден.")
        await database.execute(work_requests.update().where(work_requests.c.id == request_id).values(status="В РАБОТЕ", executor_id=response["executor_id"]))
    return {"message": "Исполнитель успешно назначен."}

@api_router.patch("/work_requests/{request_id}/status")
async def update_work_request_status(request_id: int, payload: StatusUpdate, current_user: dict = Depends(get_current_user)):
    request_db = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not request_db: raise HTTPException(status_code=404, detail="Заявка не найдена.")
    if request_db["user_id"] != current_user["id"] and request_db["executor_id"] != current_user["id"]: raise HTTPException(status_code=403, detail="У вас нет прав на изменение этой заявки.")
    valid_statuses = ["ВЫПОЛНЕНА", "ОТМЕНЕНА"]
    if payload.status not in valid_statuses: raise HTTPException(status_code=400, detail="Недопустимый статус.")
    if payload.status == "ВЫПОЛНЕНА" and not request_db["executor_id"]: raise HTTPException(status_code=400, detail="Нельзя завершить заявку, для которой не назначен исполнитель.")
    await database.execute(work_requests.update().where(work_requests.c.id == request_id).values(status=payload.status))
    return {"message": f"Статус заявки обновлен на '{payload.status}'."}

@api_router.post("/work_requests/{request_id}/rate")
async def rate_work_request(request_id: int, rating_data: RatingIn, current_user: dict = Depends(get_current_user)):
    async with database.transaction():
        req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
        if not req: raise HTTPException(status_code=404, detail="Заявка не найдена.")
        if req["status"] != "ВЫПОЛНЕНА": raise HTTPException(status_code=400, detail="Оценить можно только выполненную заявку.")
        rater_id = current_user["id"]
        rated_id = None
        if rating_data.rating_type == "TO_EXECUTOR":
            if rater_id != req["user_id"]: raise HTTPException(status_code=403, detail="Только заказчик может оценить исполнителя.")
            rated_id = req["executor_id"]
        elif rating_data.rating_type == "TO_CUSTOMER":
            if rater_id != req["executor_id"]: raise HTTPException(status_code=403, detail="Только исполнитель может оценить заказчика.")
            rated_id = req["user_id"]
        else: raise HTTPException(status_code=400, detail="Неверный тип оценки ('rating_type').")
        if not rated_id: raise HTTPException(status_code=400, detail="Не удалось определить оцениваемого пользователя.")
        if await database.fetch_one(ratings.select().where((ratings.c.work_request_id == request_id) & (ratings.c.rater_user_id == rater_id))):
            raise HTTPException(status_code=400, detail="Вы уже оставили оценку для этой заявки.")
        await database.execute(ratings.insert().values(work_request_id=request_id, rater_user_id=rater_id, rated_user_id=rated_id, rating_type=rating_data.rating_type, rating=rating_data.rating, comment=rating_data.comment))
        avg_query = select(sa_func.avg(ratings.c.rating), sa_func.count(ratings.c.id)).where(ratings.c.rated_user_id == rated_id)
        result = await database.fetch_one(avg_query)
        new_avg, new_count = (round(float(result[0] or 0), 2), result[1] or 0)
        await database.execute(users.update().where(users.c.id == rated_id).values(average_rating=new_avg, ratings_count=new_count))
    return {"message": "Оценка успешно отправлена."}


# ИСПРАВЛЕНО: Эта функция была переписана, чтобы исправить ошибку и упростить логику.
# Также был удален дублирующий POST эндпоинт.
@api_router.patch("/me/specializations/")
async def update_user_specializations(
    data: AdditionalSpecializationUpdate,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user['id']
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только исполнители могут управлять специализациями.")

    new_additional_codes = set(data.additional_codes)

    # 1. Запуск транзакции
    async with database.transaction():
        # 2. Получение текущей Основной специализации
        # ИСПРАВЛЕНО: Убраны квадратные скобки из select()
        primary_spec_query = select(performer_specializations.c.specialization_code).where(
            and_(
                performer_specializations.c.user_id == user_id,
                performer_specializations.c.is_primary == True
            )
        )
        primary_spec_result = await database.fetch_one(primary_spec_query)

        if not primary_spec_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Основная специализация пользователя не найдена."
            )

        primary_code = primary_spec_result['specialization_code']

        # Проверка: основная специализация НЕ должна быть в списке дополнительных
        if primary_code in new_additional_codes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Основная специализация не может быть выбрана как дополнительная."
            )

        # 3. Удаление ВСЕХ старых специализаций пользователя
        delete_query = performer_specializations.delete().where(
            performer_specializations.c.user_id == user_id
        )
        await database.execute(delete_query)

        # 4. Подготовка данных для вставки (основная + новые дополнительные)
        specialization_data_to_insert = []

        # Добавляем Основную специализацию
        specialization_data_to_insert.append({
            "user_id": user_id,
            "specialization_code": primary_code,
            "is_primary": True
        })

        # Добавляем Дополнительные специализации
        for code in new_additional_codes:
            specialization_data_to_insert.append({
                "user_id": user_id,
                "specialization_code": code,
                "is_primary": False
            })

        # 5. Вставка всех специализаций одним запросом
        if specialization_data_to_insert:
            insert_query = performer_specializations.insert().values(specialization_data_to_insert)
            await database.execute(insert_query)

    return {"message": "Дополнительные специализации успешно обновлены."}


# ... (Остальные CRUD эндпоинты)
@api_router.post("/machinery_requests/", status_code=status.HTTP_201_CREATED)
async def create_machinery_request(machinery_request: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    query = machinery_requests.insert().values(user_id=current_user["id"], **machinery_request.model_dump())
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **machinery_request.model_dump()}

@api_router.get("/machinery_requests/")
async def get_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select()
    if city_id: query = query.where(machinery_requests.c.city_id == city_id)
    return await database.fetch_all(query.order_by(machinery_requests.c.is_premium.desc(), machinery_requests.c.created_at.desc()))

@api_router.patch("/machinery_requests/{request_id}/take")
async def take_machinery_request(request_id: int, current_user: dict = Depends(get_current_user)):
    await database.execute(machinery_requests.update().where(machinery_requests.c.id == request_id).values(status="В РАБОТЕ", executor_id=current_user['id']))
    return {"message": "Заявка успешно принята.", "request_id": request_id}

@api_router.post("/tool_requests/", status_code=status.HTTP_201_CREATED)
async def create_tool_request(tool_request: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    query = tool_requests.insert().values(user_id=current_user["id"], **tool_request.model_dump())
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **tool_request.model_dump()}

@api_router.get("/tool_requests/")
async def get_tool_requests(city_id: Optional[int] = None):
    query = tool_requests.select()
    if city_id: query = query.where(tool_requests.c.city_id == city_id)
    return await database.fetch_all(query.order_by(tool_requests.c.created_at.desc()))

@api_router.post("/material_ads/", status_code=status.HTTP_201_CREATED)
async def create_material_ad(material_ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    query = material_ads.insert().values(user_id=current_user["id"], **material_ad.model_dump())
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **material_ad.model_dump()}

@api_router.get("/material_ads/")
async def get_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id: query = query.where(material_ads.c.city_id == city_id)
    return await database.fetch_all(query.order_by(material_ads.c.is_premium.desc(), material_ads.c.created_at.desc()))

@api_router.post("/update_specialization/") # Этот эндпоинт теперь не нужен, но оставим для совместимости. Логика переехала.
async def update_user_specialization(specialization: str, current_user: dict = Depends(get_current_user)):
     raise HTTPException(status_code=410, detail="Этот метод устарел. Используйте /api/me/specializations/")

@api_router.get("/work_requests/me/")
async def get_work_requests_for_me(current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    user_city_id = current_user.get('city_id') # Это поле не установлено у пользователя, будет None
    user_is_premium = is_user_premium(current_user)

    # 1. Получаем все специализации пользователя
    # ИСПРАВЛЕНО: Убраны квадратные скобки из select()
    spec_query = select(
        performer_specializations.c.specialization_code,
        performer_specializations.c.is_primary
    ).where(performer_specializations.c.user_id == user_id)

    user_specs = await database.fetch_all(spec_query)

    if not user_specs: return []

    # 2. Определяем список кодов специализаций, по которым разрешен просмотр
    allowed_codes = set()

    for spec in user_specs:
        if spec['is_primary'] or user_is_premium:
            allowed_codes.add(spec['specialization_code'])

    if not allowed_codes: return []
    
    # ИСПРАВЛЕНО: КРИТИЧЕСКАЯ ОШИБКА ЛОГИКИ
    # В таблице work_requests нет поля 'specialization_code', есть 'specialization' с названием.
    # Сначала нужно получить названия по кодам.
    spec_names_query = select(specializations.c.name).where(specializations.c.code.in_(list(allowed_codes)))
    allowed_names_records = await database.fetch_all(spec_names_query)
    allowed_names = [record['name'] for record in allowed_names_records]
    
    if not allowed_names: return []
    
    # 3. Формируем запрос на заявки: фильтр по городу и РАЗРЕШЕННЫМ НАЗВАНИЯМ специализаций
    # ПРИМЕЧАНИЕ: Фильтрация по городу здесь не будет работать, так как у user нет city_id.
    # Лента будет показывать заявки из всех городов, что может быть не тем, чего ты ожидаешь.
    work_query = work_requests.select().where(
        work_requests.c.specialization.in_(allowed_names)
    )
    # Если бы у пользователя был city_id, запрос выглядел бы так:
    # work_query = work_requests.select().where(
    #     and_(
    #         work_requests.c.specialization.in_(allowed_names),
    #         work_requests.c.city_id == user_city_id
    #     )
    # )

    return await database.fetch_all(work_query.order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc()))


app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)