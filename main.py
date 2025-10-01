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
# ИСПРАВЛЕНИЕ: Убедиться, что or_ импортирован для сложных запросов
from sqlalchemy import exc, or_ 
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
    username: str
    password: str
    phone_number: str
    user_type: str
    specialization: Optional[str] = None
    city_id: int

class UserOut(BaseModel):
    """Схема для выдачи данных пользователя (без пароля)."""
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
    contact_info: str
    city_id: int
    rental_start: Optional[date] = None
    rental_end: Optional[date] = None
    has_delivery: bool = False
    delivery_address: Optional[str] = None

class ToolRequestOut(BaseModel):
    """Схема для выдачи данных заявки на инструмент."""
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


# --- MATERIAL AD SCHEMAS ---
class MaterialAdIn(BaseModel):
    """Схема для создания объявления о материалах."""
    material_type: str
    description: Optional[str] = None
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


# --- CITY SCHEMAS ---
class CityOut(BaseModel):
    """Схема для выдачи данных города."""
    id: int
    name: str
    region: Optional[str] = None


# --- CHAT SCHEMAS ---
class ChatMessageIn(BaseModel):
    """Схема для отправки нового сообщения."""
    message: str

class ChatMessageOut(BaseModel):
    """Схема для выдачи сообщения."""
    id: int
    request_id: int
    sender_id: int
    message: str
    created_at: datetime


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
    
    if user_in.user_type == "worker" and not user_in.specialization:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Для исполнителя необходимо указать специализацию.")

    query = users.insert().values(
        email=user_in.email,
        username=user_in.username,
        hashed_password=hashed_password,
        phone_number=user_in.phone_number,
        user_type=user_in.user_type,
        specialization=user_in.specialization,
        city_id=user_in.city_id
    )

    try:
        last_record_id = await database.execute(query)
        created_user_query = users.select().where(users.c.id == last_record_id)
        created_user = await database.fetch_one(created_user_query)
        return created_user
    except exc.IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ошибка целостности данных (например, неверный city_id).")


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
        data={"sub": str(user["id"])}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """Получение информации о текущем пользователе."""
    return current_user


# --- CITIES ---

@api_router.get("/cities", response_model=List[CityOut])
async def get_cities():
    """Получение списка всех городов."""
    query = cities.select().order_by(cities.c.name)
    return await database.fetch_all(query)


# --- WORK REQUESTS ---

@api_router.post("/work_requests", response_model=WorkRequestOut, status_code=status.HTTP_201_CREATED)
async def create_work_request(request_in: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    """Создание новой заявки на работу."""
    if current_user["user_type"] != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только заказчики могут создавать заявки на работу.")

    query = work_requests.insert().values(
        user_id=current_user["id"],
        name=request_in.name,
        description=request_in.description,
        specialization=request_in.specialization,
        budget=request_in.budget,
        phone_number=request_in.phone_number,
        city_id=request_in.city_id,
        address=request_in.address,
        visit_date=request_in.visit_date
    )

    last_record_id = await database.execute(query)
    
    created_request_query = work_requests.select().where(work_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    return created_request


@api_router.get("/work_requests/by_city/{city_id}", response_model=List[WorkRequestOut])
async def get_work_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех не взятых заявок в определенном городе."""
    query = work_requests.select().where(
        (work_requests.c.city_id == city_id) & 
        (work_requests.c.is_taken == False)
    ).order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc())
    
    return await database.fetch_all(query)


@api_router.post("/work_requests/take/{request_id}", response_model=WorkRequestOut)
async def take_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    """Исполнитель берет заявку в работу и включает чат."""
    if current_user["user_type"] != "worker":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только рабочие могут брать заявки.")

    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)

    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена.")
    
    if request["is_taken"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заявка уже взята другим исполнителем.")

    update_query = (
        work_requests.update()
        .where(work_requests.c.id == request_id)
        .values(executor_id=current_user["id"], is_taken=True, chat_enabled=True) 
    )

    try:
        await database.execute(update_query)
    except exc.IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ошибка при обновлении заявки.")

    updated_request = await database.fetch_one(query)
    return updated_request


@api_router.get("/work_requests/my", response_model=List[WorkRequestOut])
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    """Получение заявок, созданных текущим пользователем (Заказчик) или взятых им (Рабочий)."""
    user_id = current_user["id"]
    
    query = work_requests.select().where(
        or_(
            work_requests.c.user_id == user_id,  # Заявки, которые я создал
            work_requests.c.executor_id == user_id # Заявки, которые я взял
        )
    ).order_by(work_requests.c.created_at.desc())

    return await database.fetch_all(query)

@api_router.post("/work_requests/complete/{request_id}", response_model=WorkRequestOut)
async def complete_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    """Заказчик отмечает заявку как завершенную."""
    
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(request_query)

    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена.")
    
    if request["user_id"] != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только создатель заявки может ее завершить.")
    
    if not request["is_taken"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заявка еще не взята в работу.")
    
    if request["is_completed"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Заявка уже завершена.")

    update_query = (
        work_requests.update()
        .where(work_requests.c.id == request_id)
        .values(is_completed=True) 
    )

    await database.execute(update_query)
    updated_request = await database.fetch_one(request_query)
    return updated_request

# --- CHAT ENDPOINTS ---

@api_router.get("/work_requests/{request_id}/chat", response_model=List[ChatMessageOut])
async def get_chat_messages(request_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех сообщений для конкретной заявки."""
    
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(request_query)

    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена.")

    if not request["chat_enabled"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Чат для этой заявки еще не активирован.")

    user_id = current_user["id"]
    is_requester = request["user_id"] == user_id
    is_executor = request["executor_id"] == user_id

    if not (is_requester or is_executor):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа к этому чату.")

    query = chat_messages.select().where(chat_messages.c.request_id == request_id).order_by(chat_messages.c.created_at)
    return await database.fetch_all(query)


@api_router.post("/work_requests/{request_id}/chat", response_model=ChatMessageOut, status_code=status.HTTP_201_CREATED)
async def send_chat_message(request_id: int, message_in: ChatMessageIn, current_user: dict = Depends(get_current_user)):
    """Отправка нового сообщения в чат заявки."""
    
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(request_query)

    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена.")

    if not request["chat_enabled"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Чат для этой заявки еще не активирован.")

    user_id = current_user["id"]
    is_requester = request["user_id"] == user_id
    is_executor = request["executor_id"] == user_id

    if not (is_requester or is_executor):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Вы не являетесь участником этого чата.")

    query = chat_messages.insert().values(
        request_id=request_id,
        sender_id=user_id,
        message=message_in.message,
    )

    last_record_id = await database.execute(query)
    
    created_message_query = chat_messages.select().where(chat_messages.c.id == last_record_id)
    created_message = await database.fetch_one(created_message_query)
    return created_message


# --- MACHINERY REQUESTS ENDPOINTS (ВОССТАНОВЛЕННЫЕ БЛОКИ) ---

@api_router.post("/machinery_requests", response_model=MachineryRequestOut, status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request_in: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    """Создание новой заявки на спецтехнику."""
    if current_user["user_type"] != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только заказчики могут создавать заявки.")

    query = machinery_requests.insert().values(
        user_id=current_user["id"],
        machinery_type=request_in.machinery_type,
        description=request_in.description,
        rental_price=request_in.rental_price,
        min_hours=request_in.min_hours,
        contact_info=request_in.contact_info,
        city_id=request_in.city_id,
        rental_date=request_in.rental_date
    )

    last_record_id = await database.execute(query)
    
    created_request_query = machinery_requests.select().where(machinery_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    return created_request


@api_router.get("/machinery_requests/by_city/{city_id}", response_model=List[MachineryRequestOut])
async def get_machinery_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех заявок на спецтехнику в определенном городе."""
    query = machinery_requests.select().where(machinery_requests.c.city_id == city_id).order_by(machinery_requests.c.is_premium.desc(), machinery_requests.c.created_at.desc())
    return await database.fetch_all(query)


@api_router.get("/machinery_requests/my", response_model=List[MachineryRequestOut])
async def get_my_machinery_requests(current_user: dict = Depends(get_current_user)):
    """Получение заявок на спецтехнику, созданных текущим пользователем."""
    query = machinery_requests.select().where(machinery_requests.c.user_id == current_user["id"])
    return await database.fetch_all(query)


# --- TOOL REQUESTS ENDPOINTS (ВОССТАНОВЛЕННЫЕ БЛОКИ) ---

@api_router.post("/tool_requests", response_model=ToolRequestOut, status_code=status.HTTP_201_CREATED)
async def create_tool_request(request_in: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    """Создание новой заявки на инструмент."""
    if current_user["user_type"] != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только заказчики могут создавать заявки.")

    query = tool_requests.insert().values(
        user_id=current_user["id"],
        tool_name=request_in.tool_name,
        description=request_in.description,
        rental_price=request_in.rental_price,
        tool_count=request_in.tool_count,
        contact_info=request_in.contact_info,
        city_id=request_in.city_id,
        rental_start=request_in.rental_start,
        rental_end=request_in.rental_end,
        has_delivery=request_in.has_delivery,
        delivery_address=request_in.delivery_address
    )

    last_record_id = await database.execute(query)
    
    created_request_query = tool_requests.select().where(tool_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    return created_request


@api_router.get("/tool_requests/by_city/{city_id}", response_model=List[ToolRequestOut])
async def get_tool_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех заявок на инструмент в определенном городе."""
    query = tool_requests.select().where(tool_requests.c.city_id == city_id).order_by(tool_requests.c.is_premium.desc(), tool_requests.c.created_at.desc())
    return await database.fetch_all(query)


@api_router.get("/tool_requests/my", response_model=List[ToolRequestOut])
async def get_my_tool_requests(current_user: dict = Depends(get_current_user)):
    """Получение заявок на инструмент, созданных текущим пользователем."""
    query = tool_requests.select().where(tool_requests.c.user_id == current_user["id"])
    return await database.fetch_all(query)


# --- MATERIAL ADS ENDPOINTS (ВОССТАНОВЛЕННЫЕ БЛОКИ) ---

@api_router.post("/material_ads", response_model=MaterialAdOut, status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad_in: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    """Создание нового объявления о материалах."""
    if current_user["user_type"] != "customer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только заказчики могут создавать объявления.")

    query = material_ads.insert().values(
        user_id=current_user["id"],
        material_type=ad_in.material_type,
        description=ad_in.description,
        price=ad_in.price,
        contact_info=ad_in.contact_info,
        city_id=ad_in.city_id
    )

    last_record_id = await database.execute(query)
    
    created_ad_query = material_ads.select().where(material_ads.c.id == last_record_id)
    created_ad = await database.fetch_one(created_ad_query)
    return created_ad


@api_router.get("/material_ads/by_city/{city_id}", response_model=List[MaterialAdOut])
async def get_material_ads_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    """Получение всех объявлений о материалах в определенном городе."""
    query = material_ads.select().where(material_ads.c.city_id == city_id).order_by(material_ads.c.is_premium.desc(), material_ads.c.created_at.desc())
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

@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))