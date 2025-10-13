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
from sqlalchemy.sql import select, func as sa_func
import os
from dotenv import load_dotenv
from pathlib import Path

# --- Database setup ---
# Импортируем все таблицы, включая новые, из файла database.py
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities, database, ratings, work_request_responses

load_dotenv()

base_path = Path(__file__).parent
static_path = base_path / "static"

# Настройки для токенов
SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key-that-is-long")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 часа для удобства тестирования

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

@app.on_event("startup")
async def startup():
    await database.connect()
    # metadata.create_all(engine) # В продакшене лучше управлять миграциями отдельно
    print("Database connected.")
    
    # Код для начального заполнения городов
    query = cities.select().limit(1)
    if not await database.fetch_one(query):
        print("Города не найдены, добавляю стандартный список...")
        default_cities = [{"name": "Москва"}, {"name": "Санкт-Петербург"}, {"name": "Новосибирск"}, {"name": "Екатеринбург"}, {"name": "Казань"}]
        await database.execute(cities.insert().values(default_cities))
        print("Города успешно добавлены.")

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
    print("Database disconnected.")

# --- Схемы Pydantic (модели данных) ---

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    phone_number: str
    user_type: str = Field(..., description="Тип пользователя: ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ")
    specialization: Optional[str] = None

class UserOut(BaseModel):
    id: int
    email: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None
    is_premium: bool
    average_rating: float
    ratings_count: int
    class Config: from_attributes = True

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

# ИСПРАВЛЕНА: Модель для рейтинга, теперь она одна и универсальная
class RatingIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    rating_type: str # 'TO_EXECUTOR' или 'TO_CUSTOMER'

class City(BaseModel):
    id: int
    name: str
    class Config: from_attributes = True

# ДОБАВЛЕНЫ: Модели для спецтехники, инструментов и материалов
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

# --- Утилиты для аутентификации и безопасности ---

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
    return dict(user_db) # Возвращает стандартный словарь

# --- Маршруты API ---

@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_index():
    return FileResponse(static_path / "index.html")

# --- Регистрация, логин, профиль ---

@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user_db = await authenticate_user(form_data.username, form_data.password)
    if not user_db:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль"
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_db["email"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def create_user(user: UserCreate):
    if await database.fetch_one(users.select().where(users.c.email == user.email)):
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует.")
    if user.user_type == "ИСПОЛНИТЕЛЬ" and not user.specialization:
        raise HTTPException(status_code=400, detail="Для 'ИСПОЛНИТЕЛЯ' специализация обязательна.")
    
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        email=user.email, hashed_password=hashed_password, phone_number=user.phone_number,
        user_type=user.user_type, specialization=user.specialization
    )
    user_id = await database.execute(query)
    return await database.fetch_one(users.select().where(users.c.id == user_id))

@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user

# --- Основная логика заявок на работу ---

@api_router.post("/work_requests/", status_code=status.HTTP_201_CREATED)
async def create_work_request(work_request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    query = work_requests.insert().values(user_id=current_user["id"], **work_request.model_dump())
    request_id = await database.execute(query)
    return {"id": request_id, **work_request.model_dump()}

@api_router.get("/work_requests/")
async def get_work_requests(city_id: int, current_user: dict = Depends(get_current_user)):
    """ ИСПРАВЛЕНО: Полностью переписанная и стандартизированная логика фильтрации. """
    query = work_requests.select().where(work_requests.c.city_id == city_id)
    # Показываем только заявки, которые ожидают исполнителя
    query = query.where(work_requests.c.status == "ОЖИДАЕТ")
    # Не показывать пользователю его собственные заявки в общем списке
    query = query.where(work_requests.c.user_id != current_user["id"])

    # Ключевой фильтр: если пользователь - исполнитель, он видит только свою специализацию
    if current_user["user_type"] == "ИСПОЛНИТЕЛЬ":
        specialization = current_user.get("specialization")
        if not specialization:
            return [] # У исполнителя нет специализации - он не видит ни одной заявки
        query = query.where(work_requests.c.specialization == specialization)
            
    query = query.order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.get("/users/me/requests/")
async def get_my_requests(current_user: dict = Depends(get_current_user)):
    """ ИСПРАВЛЕНО: Более чистая и правильная логика получения "моих" заявок. """
    user_id = current_user["id"]
    
    if current_user["user_type"] == "ЗАКАЗЧИК":
        # Заказчик видит все заявки, которые он создал
        query = work_requests.select().where(work_requests.c.user_id == user_id)
    
    elif current_user["user_type"] == "ИСПОЛНИТЕЛЬ":
        # Исполнитель видит и те заявки, где он назначен, и те, на которые он откликнулся
        assigned_q = select(work_requests.c.id).where(work_requests.c.executor_id == user_id)
        responded_q = select(work_request_responses.c.work_request_id).where(work_request_responses.c.executor_id == user_id)
        
        # Объединяем ID заявок без дубликатов
        all_my_request_ids = assigned_q.union(responded_q)
        query = work_requests.select().where(work_requests.c.id.in_(all_my_request_ids))
    else:
        return []

    return await database.fetch_all(query.order_by(work_requests.c.created_at.desc()))

# --- Новые эндпоинты для системы откликов ---

@api_router.post("/work_requests/{request_id}/respond", status_code=201)
async def respond_to_work_request(request_id: int, response: ResponseCreate, current_user: dict = Depends(get_current_user)):
    """ Исполнитель откликается на заявку. """
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только исполнители могут откликаться.")

    work_req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not work_req or work_req["status"] != "ОЖИДАЕТ":
        raise HTTPException(status_code=400, detail="Нельзя откликнуться на эту заявку (она неактивна).")

    try:
        await database.execute(work_request_responses.insert().values(
            work_request_id=request_id, executor_id=current_user["id"], comment=response.comment
        ))
    except exc.IntegrityError: # Сработает UniqueConstraint, если уже откликался
        raise HTTPException(status_code=400, detail="Вы уже откликались на эту заявку.")
    
    return {"message": "Вы успешно откликнулись на заявку."}

@api_router.get("/work_requests/{request_id}/responses", response_model=List[ResponseOut])
async def get_work_request_responses(request_id: int, current_user: dict = Depends(get_current_user)):
    """ Заказчик смотрит отклики на свою заявку. """
    work_req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not work_req or work_req["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Это не ваша заявка.")

    query = work_request_responses.join(users, work_request_responses.c.executor_id == users.c.id).select().with_only_columns([
        users.c.id, users.c.email, users.c.phone_number, users.c.user_type, users.c.specialization,
        users.c.is_premium, users.c.average_rating, users.c.ratings_count,
        work_request_responses.c.id.label("response_id"),
        work_request_responses.c.comment.label("response_comment"),
        work_request_responses.c.created_at.label("response_created_at")
    ]).where(work_request_responses.c.work_request_id == request_id)

    return await database.fetch_all(query)

@api_router.patch("/work_requests/{request_id}/responses/{response_id}/approve")
async def approve_work_request_response(request_id: int, response_id: int, current_user: dict = Depends(get_current_user)):
    """ Заказчик утверждает исполнителя, что меняет статус заявки. """
    async with database.transaction():
        work_req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
        if not work_req or work_req["user_id"] != current_user["id"] or work_req["status"] != "ОЖИДАЕТ":
            raise HTTPException(status_code=403, detail="Невозможно назначить исполнителя для этой заявки.")

        response = await database.fetch_one(work_request_responses.select().where(work_request_responses.c.id == response_id))
        if not response or response["work_request_id"] != request_id:
            raise HTTPException(status_code=404, detail="Отклик не найден.")
        
        # Обновляем заявку: ставим статус "В РАБОТЕ" и назначаем ID исполнителя
        await database.execute(work_requests.update().where(work_requests.c.id == request_id).values(
            status="В РАБОТЕ", executor_id=response["executor_id"]
        ))
    return {"message": "Исполнитель успешно назначен."}

# --- Управление статусом и рейтинг ---

@api_router.patch("/work_requests/{request_id}/status")
async def update_work_request_status(request_id: int, new_status: str, current_user: dict = Depends(get_current_user)): # В Pydantic модели Body было бы лучше
    # ... (старые проверки остаются)
    if not request_db:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")
    if request_db["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="У вас нет прав на изменение этой заявки.")
        
    valid_statuses = ["ВЫПОЛНЕНА", "ОТМЕНЕНА"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Недопустимый статус.")

    # ===== НОВАЯ ПРОВЕРКА =====
    if new_status == "ВЫПОЛНЕНА" and not request_db["executor_id"]:
        raise HTTPException(
            status_code=400,
            detail="Нельзя завершить заявку, для которой не назначен исполнитель."
        )
    # ==========================

    await database.execute(work_requests.update().where(work_requests.c.id == request_id).values(status=new_status))
    return {"message": f"Статус заявки обновлен на '{new_status}'."}

@api_router.post("/work_requests/{request_id}/rate")
async def rate_work_request(request_id: int, rating_data: RatingIn, current_user: dict = Depends(get_current_user)):
    """ ИСПРАВЛЕНО: Полностью переписанная, безопасная и корректная логика рейтинга. """
    async with database.transaction():
        req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
        if not req:
            raise HTTPException(status_code=404, detail="Заявка не найдена.")
        
        # Оценить можно только ВЫПОЛНЕННУЮ заявку
        if req["status"] != "ВЫПОЛНЕНА":
            raise HTTPException(status_code=400, detail="Оценить можно только выполненную заявку.")

        rater_id = current_user["id"]
        rated_id = None

        # Определяем, кто кого оценивает
        if rating_data.rating_type == "TO_EXECUTOR":
            if rater_id != req["user_id"]: raise HTTPException(status_code=403, detail="Только заказчик может оценить исполнителя.")
            rated_id = req["executor_id"]
        elif rating_data.rating_type == "TO_CUSTOMER":
            if rater_id != req["executor_id"]: raise HTTPException(status_code=403, detail="Только исполнитель может оценить заказчика.")
            rated_id = req["user_id"]
        else:
            raise HTTPException(status_code=400, detail="Неверный тип оценки ('rating_type').")
        
        if not rated_id:
            raise HTTPException(status_code=400, detail="Не удалось определить оцениваемого пользователя.")

        # Проверяем, не оставлял ли этот пользователь уже оценку для этой заявки
        if await database.fetch_one(ratings.select().where(
            (ratings.c.work_request_id == request_id) & (ratings.c.rater_user_id == rater_id)
        )):
            raise HTTPException(status_code=400, detail="Вы уже оставили оценку для этой заявки.")
        
        # Вставляем новую оценку в таблицу ratings
        await database.execute(ratings.insert().values(
            work_request_id=request_id, rater_user_id=rater_id, rated_user_id=rated_id,
            rating_type=rating_data.rating_type, rating=rating_data.rating, comment=rating_data.comment
        ))

        # Пересчитываем средний рейтинг для пользователя, которому поставили оценку
        # Это более эффективно делать через агрегирующие функции SQL
        avg_query = select(sa_func.avg(ratings.c.rating), sa_func.count(ratings.c.id)).where(ratings.c.rated_user_id == rated_id)
        result = await database.fetch_one(avg_query)
        new_avg = round(float(result[0] or 0), 2)
        new_count = result[1] or 0

        # Обновляем профиль пользователя
        await database.execute(users.update().where(users.c.id == rated_id).values(
            average_rating=new_avg, ratings_count=new_count
        ))

    return {"message": "Оценка успешно отправлена."}

# --- Справочники (без изменений) ---
@api_router.get("/cities/", response_model=List[City])
async def get_cities():
    return await database.fetch_all(cities.select().order_by(cities.c.name))

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

@api_router.get("/tool_names/")
async def get_tool_names():
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

# --- Остальные эндпоинты (с исправлением) ---

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