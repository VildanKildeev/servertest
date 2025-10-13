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
from sqlalchemy import exc, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import select, func as sa_func # Используем alias для func, чтобы не конфликтовать с func из database.py
import os
from dotenv import load_dotenv
from pathlib import Path


# --- Database setup ---
# Импортируем все таблицы и метаданды из файла database.py
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities, database, ratings # Добавили 'ratings'

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
    user_type: str
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False # ✅ ИСПРАВЛЕНО
    average_rating: float = 0.0
    ratings_count: int = 0
    class Config: from_attributes = True

# Обновленная модель для вывода пользователя
class UserOut(BaseModel):
    id: int
    email: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False # ✅ ИСПРАВЛЕНО
    average_rating: float = 0.0
    ratings_count: int = 0
    class Config: from_attributes = Tr
        
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
    class Config: from_attributes = True

# НОВАЯ СХЕМА ДЛЯ РЕЙТИНГА
class RatingCreate(BaseModel):
    rating_value: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

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

@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_index():
    return FileResponse(static_path / "index.html")

@api_router.get("/cities/", response_model=List[City])
async def get_cities():
    query = cities.select().order_by(cities.c.name)
    return await database.fetch_all(query)

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
    user_id = current_user["id"]
    
    query = users.select().where(users.c.id == user_id)
    user_record = await database.fetch_one(query)
    
    if not user_record:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    # Просто возвращаем запись. Модель Pydantic `UserOut` сама отфильтрует
    # ненужные поля (например, `hashed_password`) и включит нужные (`average_rating`).
    # Это самый правильный и эффективный способ.
    return user_record

@api_router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def create_user(user: UserCreate, background_tasks: BackgroundTasks):
    query_check = users.select().where(users.c.email == user.email)
    if await database.fetch_one(query_check):
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
    return {"id": last_record_id, **work_request.model_dump()}

@api_router.get("/work_requests/")
async def get_work_requests(city_id: Optional[int] = None):
    query = work_requests.select()
    if city_id:
        query = query.where(work_requests.c.city_id == city_id)
    query = query.where(work_requests.c.status != "ВЫПОЛНЕНА") # Исключаем выполненные
    query = query.order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.get("/users/me/requests/")
async def get_my_requests(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    
    # Заявки, созданные пользователем (Заказчик) или где он исполнитель
    query = work_requests.select().where(
        (work_requests.c.user_id == user_id) | (work_requests.c.executor_id == user_id)
    )
    all_requests = await database.fetch_all(query)

    return sorted(all_requests, key=lambda x: x["created_at"], reverse=True)

@api_router.patch("/work_requests/{request_id}/take")
async def take_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только исполнители могут принимать заявки.")

    query_select = work_requests.select().where(work_requests.c.id == request_id)
    request_db = await database.fetch_one(query_select)

    if not request_db:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")
    
    if request_db["status"] != "ОЖИДАЕТ":
        raise HTTPException(status_code=400, detail=f"Заявка имеет статус '{request_db['status']}' и не может быть принята.")

    user_id = current_user['id']
    query_update = work_requests.update().where(work_requests.c.id == request_id).values(status="В РАБОТЕ", executor_id=user_id)
    await database.execute(query_update)
    
    return {"message": "Заявка успешно принята.", "request_id": request_id}

@api_router.patch("/work_requests/{request_id}/status")
async def update_work_request_status(request_id: int, new_status: str, current_user: dict = Depends(get_current_user)):
    query_select = work_requests.select().where(work_requests.c.id == request_id)
    request_db = await database.fetch_one(query_select)

    if not request_db:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")
    
    if request_db["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Только заказчик может менять статус этой заявки.")
        
    valid_statuses = ["ВЫПОЛНЕНА", "ОТМЕНЕНА"] # Заказчик не может вернуть в работу
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Недопустимый статус: {new_status}. Разрешены: {', '.join(valid_statuses)}")

    query_update = work_requests.update().where(work_requests.c.id == request_id).values(status=new_status)
    await database.execute(query_update)
    
    return {"message": f"Статус заявки #{request_id} обновлен до '{new_status}'.", "request_id": request_id}

# ===========================================================================
# НОВЫЙ МАРШРУТ: Оценка выполненной работы (Заказчик -> Исполнителю)
# ===========================================================================
@api_router.post("/work_requests/{request_id}/rate", status_code=status.HTTP_201_CREATED)
async def rate_work_request(request_id: int, rating: RatingCreate, current_user: dict = Depends(get_current_user)):
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    work_request = await database.fetch_one(request_query)

    if not work_request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    if work_request["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Вы не являетесь заказчиком этой работы и не можете ее оценить.")

    if work_request["status"] != "ВЫПОЛНЕНА":
        raise HTTPException(status_code=400, detail="Оценить можно только выполненные заявки со статусом 'ВЫПОЛНЕНА'.")

    rating_check_query = ratings.select().where(ratings.c.work_request_id == request_id)
    if await database.fetch_one(rating_check_query):
        raise HTTPException(status_code=400, detail="Эта заявка уже оценена.")
        
    executor_id = work_request["executor_id"]
    if not executor_id:
         raise HTTPException(status_code=400, detail="У заявки нет исполнителя для оценки.")

    async with database.transaction():
        insert_rating_query = ratings.insert().values(
            work_request_id=request_id,
            rater_id=current_user["id"],
            rated_id=executor_id,
            rating_value=rating.rating_value,
            comment=rating.comment,
        )
        await database.execute(insert_rating_query)
        
        aggregate_query = select(
            [sa_func.count(ratings.c.id).label('total_count'), sa_func.sum(ratings.c.rating_value).label('total_sum')]
        ).where(ratings.c.rated_id == executor_id)
        
        result = await database.fetch_one(aggregate_query)
        
        total_count = result['total_count'] if result and result['total_count'] is not None else 0
        total_sum = result['total_sum'] if result and result['total_sum'] is not None else 0
        new_average = round(total_sum / total_count, 2) if total_count > 0 else 0.0

        update_user_query = users.update().where(users.c.id == executor_id).values(
            average_rating=new_average,
            ratings_count=total_count
        )
        await database.execute(update_user_query)

    return {"message": "Исполнитель успешно оценен", "average_rating": new_average}

@api_router.get("/specializations/")
async def get_specializations():
    return [
        {"id": 1, "name": "Электрик"}, {"id": 2, "name": "Сантехник"},
        {"id": 3, "name": "Плотник"}, {"id": 4, "name": "Мастер на час"},
        {"id": 5, "name": "Отделочник"}, {"id": 6, "name": "Сварщик"},
        {"id": 7, "name": "Грузчик"},
    ]

@api_router.get("/machinery_types/")
async def get_machinery_types():
    return [
        {"id": 1, "name": "Экскаватор-погрузчик"}, {"id": 2, "name": "Автокран"},
        {"id": 3, "name": "Самосвал"}, {"id": 4, "name": "Манипулятор"},
        {"id": 5, "name": "Компрессор"},
    ]

@api_router.get("/tools_list/")
async def get_tools_list():
    return [
        {"id": 1, "name": "Отбойный молоток"}, {"id": 2, "name": "Бетономешалка"},
        {"id": 3, "name": "Виброплита"}, {"id": 4, "name": "Перфоратор (мощный)"},
        {"id": 5, "name": "Сварочный аппарат"},
    ]

@api_router.get("/material_types/")
async def get_material_types():
    return [
        {"id": 1, "name": "Кирпич"}, {"id": 2, "name": "Цемент"},
        {"id": 3, "name": "Песок"}, {"id": 4, "name": "Щебень"},
        {"id": 5, "name": "Пиломатериалы"},
    ]

# --- Остальные эндпоинты (без изменений) ---

# Создание запроса на спецтехнику
@api_router.post("/machinery_requests/", status_code=status.HTTP_201_CREATED)
async def create_machinery_request(machinery_request: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = machinery_requests.insert().values(
        user_id=user_id, machinery_type=machinery_request.machinery_type,
        description=machinery_request.description, rental_price=machinery_request.rental_price,
        contact_info=machinery_request.contact_info, city_id=machinery_request.city_id,
        is_premium=machinery_request.is_premium, rental_date=machinery_request.rental_date,
        min_rental_hours=machinery_request.min_rental_hours, has_delivery=machinery_request.has_delivery,
        delivery_address=machinery_request.delivery_address,
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **machinery_request.model_dump()}

@api_router.get("/machinery_requests/")
async def get_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select()
    if city_id:
        query = query.where(machinery_requests.c.city_id == city_id)
    query = query.order_by(machinery_requests.c.is_premium.desc(), machinery_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.patch("/machinery_requests/{request_id}/take")
async def take_machinery_request(request_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user['id']
    query_update = machinery_requests.update().where(machinery_requests.c.id == request_id).values(status="В РАБОТЕ", executor_id=user_id)
    await database.execute(query_update)
    return {"message": "Заявка успешно принята.", "request_id": request_id}

@api_router.post("/tool_requests/", status_code=status.HTTP_201_CREATED)
async def create_tool_request(tool_request: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = tool_requests.insert().values(
        user_id=user_id, tool_name=tool_request.tool_name, description=tool_request.description,
        rental_price=tool_request.rental_price, contact_info=tool_request.contact_info,
        city_id=tool_request.city_id, count=tool_request.count, rental_start_date=tool_request.rental_start_date,
        rental_end_date=tool_request.rental_end_date, has_delivery=tool_request.has_delivery,
        delivery_address=tool_request.delivery_address,
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **tool_request.model_dump()}

@api_router.get("/tool_requests/")
async def get_tool_requests(city_id: Optional[int] = None):
    query = tool_requests.select()
    if city_id:
        query = query.where(tool_requests.c.city_id == city_id)
    query = query.order_by(tool_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.post("/material_ads/", status_code=status.HTTP_201_CREATED)
async def create_material_ad(material_ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = material_ads.insert().values(
        user_id=user_id, material_type=material_ad.material_type, description=material_ad.description,
        price=material_ad.price, contact_info=material_ad.contact_info, city_id=material_ad.city_id,
        is_premium=material_ad.is_premium,
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, **material_ad.model_dump()}

@api_router.get("/material_ads/")
async def get_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id:
        query = query.where(material_ads.c.city_id == city_id)
    query = query.order_by(material_ads.c.is_premium.desc(), material_ads.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.post("/subscribe/")
async def activate_premium_subscription(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    query = users.update().where(users.c.id == user_id).values(is_premium=True)
    await database.execute(query)
    return {"message": "Премиум-подписка активирована."}

@api_router.post("/update_specialization/")
async def update_user_specialization(specialization: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Специализация может быть обновлена только для исполнителей.")
    query = users.update().where(users.c.id == user_id).values(specialization=specialization)
    await database.execute(query)
    return {"message": "Специализация успешно обновлена."}

app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)