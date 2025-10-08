import uvicorn
import databases
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from typing import Optional, List, Dict 
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter 
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import select
import os
from dotenv import load_dotenv
from pathlib import Path
import sqlalchemy

# Импорты только необходимых таблиц
from database import (
    metadata, engine, users, work_requests, machinery_requests, tool_requests, 
    material_ads, cities, database, specializations, machinery_types, 
    tool_types, material_types, initial_cities, initial_specializations, 
    initial_machinery_types, initial_tool_types, initial_material_types
)

load_dotenv()


# Настройки для токенов
SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
# Увеличен до 24 часов для удобства
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 

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
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # Используем глобальную переменную
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# ОБНОВЛЕНО: Получение is_premium из базы данных
async def get_current_user(token: str = Depends(oauth2_scheme)):
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
    
    # Запрос всех данных пользователя, включая is_premium
    query = users.select().where(users.c.id == int(user_id))
    user = await database.fetch_one(query)
    if user is None:
        raise credentials_exception
    # Возвращаем dict для легкого доступа к полям
    return dict(user)


async def is_email_taken(email: str) -> bool:
    query = users.select().where(users.c.email == email)
    user = await database.fetch_one(query)
    return user is not None

# Функция для заполнения справочников
async def populate_reference_table(table, initial_data):
    count_query = select(sqlalchemy.func.count()).select_from(table) 
    count = await database.fetch_val(count_query)

    if count == 0:
        print(f"Заполнение таблицы {table.name}...")
        query = table.insert()
        await database.execute_many(query, initial_data)
        print(f"Таблица {table.name} заполнена {len(initial_data)} записями.")


@app.on_event("startup")
async def startup():
    metadata.create_all(engine)
    print("Connecting to the database...")
    await database.connect()
    
    # Заполнение справочников при первом запуске
    await populate_reference_table(cities, initial_cities)
    await populate_reference_table(specializations, initial_specializations)
    await populate_reference_table(machinery_types, initial_machinery_types)
    await populate_reference_table(tool_types, initial_tool_types)
    await populate_reference_table(material_types, initial_material_types)


@app.on_event("shutdown")
async def shutdown():
    print("Disconnecting from the database...")
    await database.disconnect()


# ----------------------------------------------------
# --- Schemas ---
# ----------------------------------------------------

class UserIn(BaseModel):
    email: EmailStr
    password: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None
    city_id: int
    first_name: str

class UserOut(BaseModel):
    id: int
    email: EmailStr
    first_name: str
    phone_number: str
    is_active: Optional[bool] = True
    created_at: datetime
    city_id: Optional[int] = None
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False # is_premium
    user_type: str
    rating: Optional[float] = Field(None, description="Рейтинг пользователя", ge=0.0, le=5.0)
    rating_count: Optional[int] = Field(None, description="Количество оценок", ge=0)
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

# --- WORK REQUESTS SCHEMAS ---
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
    phone_number: str # Будет маскироваться
    city_id: int
    created_at: datetime
    is_taken: bool
    address: Optional[str]
    visit_date: Optional[datetime]
    is_premium: Optional[bool] # Premium-статус создателя заявки


# --- MACHINERY REQUESTS SCHEMAS ---
class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float  # Цена за час
    contact_info: str
    city_id: int
    # Новые поля
    rental_date: date
    min_hours_4: bool = False # Изменено на False (для чекбокса)
    hours_count: int
    delivery_date: Optional[date] = None # ДОБАВЛЕНО: Дата доставки

class MachineryRequestOut(BaseModel):
    id: int
    user_id: int
    machinery_type: str
    description: Optional[str]
    rental_price: float
    contact_info: str
    city_id: int
    created_at: datetime
    is_premium: Optional[bool]
    # Новые поля
    rental_date: Optional[date]
    min_hours_4: Optional[bool]
    hours_count: Optional[int]
    delivery_date: Optional[date] # ДОБАВЛЕНО: Дата доставки
    
    class Config:
        from_attributes = True

# --- TOOL REQUESTS SCHEMAS ---
class ToolRequestIn(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float # Цена в сутки
    contact_info: str
    city_id: int
    # Новые поля
    rental_start_date: date
    rental_end_date: date
    has_delivery: bool = False
    delivery_address: Optional[str] = None

class ToolRequestOut(BaseModel):
    id: int
    user_id: int
    tool_name: str
    description: Optional[str]
    rental_price: float
    contact_info: str
    city_id: int
    created_at: datetime
    is_premium: Optional[bool]
    # Новые поля
    rental_start_date: Optional[date]
    rental_end_date: Optional[date]
    has_delivery: Optional[bool]
    delivery_address: Optional[str]

    class Config:
        from_attributes = True

# --- MATERIAL ADS SCHEMAS ---
class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str]
    price: float
    contact_info: str # Будет маскироваться
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

# --- UTILITY SCHEMAS ---
class SpecializationUpdate(BaseModel):
    specialization: str

class CityOut(BaseModel):
    id: int
    name: str

class ReferenceOut(BaseModel):
    id: int
    name: str

class RatingIn(BaseModel):
    rating_value: int = Field(..., ge=1, le=5)


# ----------------------------------------------------
# --- API endpoints ---
# ----------------------------------------------------

# ОБНОВЛЕНО: Добавление is_premium в токен
@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    query = users.select().where(users.c.email == form_data.username)
    user = await database.fetch_one(query)
    
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Включаем is_premium в токен
    access_token = create_access_token(
        data={"sub": str(user["id"]), "is_premium": user["is_premium"]}, 
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@api_router.post("/register", response_model=UserOut)
async def create_user(user: UserIn):
    if user.user_type not in ["ЗАКАЗЧИК", "ИСПОЛНИТЕЛЬ"]:
        raise HTTPException(status_code=400, detail="Invalid user_type")

    check_query = users.select().where((users.c.email == user.email) | (users.c.phone_number == user.phone_number))
    if await database.fetch_one(check_query):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail="Пользователь с таким email или номером телефона уже существует."
        )

    if user.user_type == "ИСПОЛНИТЕЛЬ" and not user.specialization:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для типа 'ИСПОЛНИТЕЛЬ' поле 'specialization' обязательно."
        )

    if not user.phone_number:
        raise HTTPException(status_code=400, detail="Поле 'phone_number' обязательно.")
    if not user.first_name:
        raise HTTPException(status_code=400, detail="Поле 'first_name' обязательно.")

    specialization_to_insert = user.specialization if user.user_type == "ИСПОЛНИТЕЛЬ" else None

    hashed_password = get_password_hash(user.password)
    
    query = users.insert().values(
        email=user.email,
        hashed_password=hashed_password,
        user_type=user.user_type,
        phone_number=user.phone_number,
        specialization=specialization_to_insert,
        city_id=user.city_id,
        is_premium=False, # По умолчанию False
        rating=0.0,
        rating_count=0,
        first_name=user.first_name 
    )
    
    last_record_id = await database.execute(query)
    created_user_query = users.select().where(users.c.id == last_record_id)
    created_user = await database.fetch_one(created_user_query)
    
    return created_user

@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return UserOut(**current_user)

@api_router.post("/work_requests/{request_id}/rate")
async def rate_executor(request_id: int, rating: RatingIn, current_user: dict = Depends(get_current_user)):
    # Логика оценки исполнителя
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(request_query)
    if not request:
        raise HTTPException(status_code=404, detail="Заявка на работу не найдена.")
    if current_user["id"] != request["user_id"]:
        raise HTTPException(status_code=403, detail="Только заказчик может поставить оценку.")
    if not request["is_taken"] or request["executor_id"] is None:
        raise HTTPException(status_code=400, detail="Заявка должна быть взята в работу исполнителем.")
    
    executor_id = request["executor_id"]
    executor_query = users.select().where(users.c.id == executor_id)
    executor = await database.fetch_one(executor_query)
    if not executor:
        raise HTTPException(status_code=404, detail="Исполнитель не найден.")
    
    old_total_rating = (executor["rating"] or 0.0) * (executor["rating_count"] or 0)
    new_rating_count = (executor["rating_count"] or 0) + 1
    new_total_rating = old_total_rating + rating.rating_value
    new_average_rating = new_total_rating / new_rating_count

    update_query = users.update().where(users.c.id == executor_id).values(
        rating=new_average_rating,
        rating_count=new_rating_count
    )
    await database.execute(update_query)
    
    return {"message": f"Исполнитель {executor['email']} успешно оценен. Новый средний рейтинг: {new_average_rating:.2f}"}


# --- ENDPOINTS FOR REFERENCE DATA (CITIES, SPECIALIZATIONS, etc.) ---

@api_router.get("/cities/", response_model=List[CityOut])
async def get_cities():
    """Получает список городов."""
    query = cities.select().order_by(cities.c.name)
    return await database.fetch_all(query)

@api_router.get("/specializations/", response_model=List[ReferenceOut])
async def get_specializations():
    """Получает список специализаций."""
    query = specializations.select().order_by(specializations.c.name)
    return await database.fetch_all(query)

@api_router.get("/machinery_types/", response_model=List[ReferenceOut])
async def get_machinery_types():
    """Получает список типов спецтехники."""
    query = machinery_types.select().order_by(machinery_types.c.name)
    return await database.fetch_all(query)

@api_router.get("/tool_types/", response_model=List[ReferenceOut])
async def get_tool_types():
    """Получает список типов инструментов."""
    query = tool_types.select().order_by(tool_types.c.name)
    return await database.fetch_all(query)

@api_router.get("/material_types/", response_model=List[ReferenceOut])
async def get_material_types():
    """Получает список типов материалов."""
    query = material_types.select().order_by(material_types.c.name)
    return await database.fetch_all(query)


# --- WORK REQUESTS ENDPOINTS ---
@api_router.post("/work_requests", response_model=WorkRequestOut)
async def create_work_request(request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК может создавать заявки.")
    
    query = work_requests.insert().values(
        user_id=current_user["id"],
        name=request.name,
        description=request.description,
        specialization=request.specialization,
        budget=request.budget,
        phone_number=request.phone_number,
        city_id=request.city_id,
        address=request.address,
        visit_date=request.visit_date
    )
    last_record_id = await database.execute(query)
    
    # Получаем созданную заявку, чтобы вернуть ее с id и датой
    created_request_query = work_requests.select().where(work_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)

    # Добавляем статус is_premium создателя заявки для вывода
    request_dict = dict(created_request)
    request_dict["is_premium"] = current_user["is_premium"]

    return WorkRequestOut(**request_dict)

# ОБНОВЛЕНО: Сортировка по is_premium и маскировка телефона
@api_router.get("/work_requests/by_city/{city_id}", response_model=List[WorkRequestOut])
async def get_work_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получает и сортирует заявки на работу (премиум-заявки выше), маскируя телефон для обычных пользователей."""
    
    # 1. Формируем запрос с JOIN для получения статуса Premium создателя заявки (для сортировки)
    join_clause = work_requests.join(users, work_requests.c.user_id == users.c.id)
    
    # Выбираем колонки work_requests и статус is_premium пользователя (переименованный)
    query = select(
        work_requests, 
        users.c.is_premium.label("request_is_premium")
    ).select_from(join_clause).where(
        (work_requests.c.city_id == city_id) & (work_requests.c.is_taken == False)
    )

    # 2. Сортировка: сначала заявки от Premium-пользователей (True=1), затем по дате
    query = query.order_by(
        users.c.is_premium.desc(), 
        work_requests.c.created_at.desc()
    )

    requests = await database.fetch_all(query)
    
    # 3. Применяем маскировку номера на основе статуса *текущего* пользователя
    is_premium_user = current_user.get("is_premium", False)
    
    result_list = []
    for req in requests:
        req_dict = dict(req)
        
        # Переносим статус Premium создателя заявки в поле схемы WorkRequestOut
        req_dict["is_premium"] = req_dict.pop("request_is_premium", False)
        
        # Если текущий пользователь не Premium, маскируем номер
        if not is_premium_user:
            req_dict["phone_number"] = "ПРЕМИУМ ДОСТУП"
            
        result_list.append(WorkRequestOut(**req_dict))

    return result_list

@api_router.get("/work_requests/my", response_model=List[WorkRequestOut])
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    """Получить заявки, созданные текущим пользователем (Заказчик) ИЛИ заявки, которые он выполняет (Исполнитель)."""
    user_id = current_user["id"]
    
    # 1. Заявки, созданные пользователем (Заказчик)
    owner_query = work_requests.select().where(work_requests.c.user_id == user_id)
    
    # 2. Заявки, которые выполняет пользователь (Исполнитель)
    executor_query = work_requests.select().where(work_requests.c.executor_id == user_id)
    
    # Объединяем и сортируем по дате создания
    # Здесь не нужна маскировка, так как пользователь сам создал или взял заявку
    combined_query = owner_query.union(executor_query).order_by(work_requests.c.created_at.desc())
    
    requests = await database.fetch_all(combined_query)
    
    # Добавляем is_premium создателя в результат (для созданных им заявок)
    result_list = []
    for req in requests:
        req_dict = dict(req)
        # Устанавливаем статус is_premium создателя
        req_dict["is_premium"] = current_user.get("is_premium", False) if req["user_id"] == user_id else None
        result_list.append(WorkRequestOut(**req_dict))
        
    return result_list


# --- MACHINERY ENDPOINTS ---
# ОБНОВЛЕНО: Сохранение is_premium И delivery_date
@api_router.post("/machinery_requests/", response_model=MachineryRequestOut)
async def create_machinery_request(ad: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        user_id=current_user["id"],
        machinery_type=ad.machinery_type,
        description=ad.description,
        rental_price=ad.rental_price,
        contact_info=ad.contact_info,
        city_id=ad.city_id,
        # Новые поля
        rental_date=ad.rental_date,
        min_hours_4=ad.min_hours_4,
        hours_count=ad.hours_count,
        delivery_date=ad.delivery_date, # ИСПРАВЛЕНИЕ: Добавлено сохранение delivery_date
        is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    created_ad_query = machinery_requests.select().where(machinery_requests.c.id == last_record_id)
    return await database.fetch_one(created_ad_query)

# ОБНОВЛЕНО: Сортировка по is_premium и маскировка контакта
@api_router.get("/machinery_requests/by_city/{city_id}", response_model=List[MachineryRequestOut])
async def get_machinery_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получает и сортирует объявления о спецтехнике, маскируя контакт для обычных пользователей."""
    is_premium_user = current_user.get("is_premium", False)

    query = machinery_requests.select().where(machinery_requests.c.city_id == city_id)
    # Сортировка: Premium-объявления выше
    query = query.order_by(machinery_requests.c.is_premium.desc(), machinery_requests.c.created_at.desc()) 
    
    ads = await database.fetch_all(query)
    
    result_list = []
    for ad in ads:
        ad_dict = dict(ad)
        
        # Маскировка контакта
        if not is_premium_user:
            ad_dict["contact_info"] = "ПРЕМИУМ ДОСТУП"
            
        result_list.append(MachineryRequestOut(**ad_dict))

    return result_list

# --- TOOL ENDPOINTS ---
@api_router.post("/tool_requests/", response_model=ToolRequestOut)
async def create_tool_request(ad: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    query = tool_requests.insert().values(
        user_id=current_user["id"], 
        tool_name=ad.tool_name, 
        description=ad.description,
        rental_price=ad.rental_price, 
        contact_info=ad.contact_info,
        city_id=ad.city_id,
        # Новые поля
        rental_start_date=ad.rental_start_date, 
        rental_end_date=ad.rental_end_date,
        has_delivery=ad.has_delivery,
        delivery_address=ad.delivery_address if ad.has_delivery else None,
        is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    created_ad_query = tool_requests.select().where(tool_requests.c.id == last_record_id)
    return await database.fetch_one(created_ad_query)

# ОБНОВЛЕНО: Маскировка контакта
@api_router.get("/tool_requests/by_city/{city_id}", response_model=List[ToolRequestOut])
async def get_tool_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получает объявления об инструментах, маскируя контакт для обычных пользователей."""
    is_premium_user = current_user.get("is_premium", False)

    query = tool_requests.select().where(tool_requests.c.city_id == city_id).order_by(tool_requests.c.created_at.desc())
    ads = await database.fetch_all(query)
    
    result_list = []
    for ad in ads:
        ad_dict = dict(ad)
        
        # Маскировка контакта
        if not is_premium_user:
            ad_dict["contact_info"] = "ПРЕМИУМ ДОСТУП"
            
        result_list.append(ToolRequestOut(**ad_dict))

    return result_list

# --- MATERIAL ENDPOINTS ---
# ОБНОВЛЕНО: Сохранение is_premium
@api_router.post("/material_ads", response_model=MaterialAdOut)
async def create_material_ad(ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    query = material_ads.insert().values(
        user_id=current_user["id"], material_type=ad.material_type, description=ad.description,
        price=ad.price, contact_info=ad.contact_info, city_id=ad.city_id, 
        is_premium=current_user["is_premium"] # СОХРАНЯЕМ is_premium
    )
    last_record_id = await database.execute(query)
    created_ad_query = material_ads.select().where(material_ads.c.id == last_record_id)
    return await database.fetch_one(created_ad_query)

# ОБНОВЛЕНО: Сортировка по is_premium и маскировка контакта
@api_router.get("/material_ads/by_city/{city_id}", response_model=List[MaterialAdOut])
async def get_material_ads_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получает и сортирует объявления о материалах, маскируя контакт для обычных пользователей."""
    is_premium_user = current_user.get("is_premium", False)

    query = material_ads.select().where(material_ads.c.city_id == city_id)
    # Сортировка: Premium-объявления выше
    query = query.order_by(material_ads.c.is_premium.desc(), material_ads.c.created_at.desc()) 
    
    ads = await database.fetch_all(query)
    
    result_list = []
    for ad in ads:
        ad_dict = dict(ad)
        
        # Маскировка контакта
        if not is_premium_user:
            ad_dict["contact_info"] = "ПРЕМИУМ ДОСТУП"
            
        result_list.append(MaterialAdOut(**ad_dict))

    return result_list


@api_router.get("/material_ads/my", response_model=List[MaterialAdOut])
async def get_my_material_ads(current_user: dict = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.user_id == current_user["id"])
    return await database.fetch_all(query)

# --- General "My Ads" Endpoint ---
@api_router.get("/my_ads", response_model=List[Dict])
async def get_all_my_ads(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    all_ads = []

    # 1. Machinery Requests
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == user_id)
    machinery_ads = await database.fetch_all(machinery_query)
    for ad in machinery_ads:
        ad_dict = dict(ad)
        ad_dict["type"] = "machinery"
        all_ads.append(ad_dict)

    # 2. Tool Requests
    tool_query = tool_requests.select().where(tool_requests.c.user_id == user_id)
    tool_ads = await database.fetch_all(tool_query)
    for ad in tool_ads:
        ad_dict = dict(ad)
        ad_dict["type"] = "tool"
        all_ads.append(ad_dict)

    # 3. Material Ads
    material_query = material_ads.select().where(material_ads.c.user_id == user_id)
    material_ads_list = await database.fetch_all(material_query)
    for ad in material_ads_list:
        ad_dict = dict(ad)
        ad_dict["type"] = "material"
        all_ads.append(ad_dict)
        
    # Сортируем все объявления по дате создания
    return sorted(all_ads, key=lambda x: x['created_at'], reverse=True)


app.include_router(api_router)

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


# ----------------------------------------------------
# --- Static Files Mounting ---
# ----------------------------------------------------

# Определяем путь к папке 'static'
static_dir = Path(__file__).parent / "static"

# Проверяем существование папки static
if static_dir.is_dir():
    # Монтируем папку 'static' К КОРНЕВОМУ URL ("/")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static_spa")

if __name__ == "__main__":
    # Исправлена ошибка: uvicorn.run должен использовать app, а не "main:app" в этом блоке
    # Но для использования "main:app" при запуске через консоль, оставим как было, 
    # чтобы не нарушать стандартный способ запуска FastAPI.
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)