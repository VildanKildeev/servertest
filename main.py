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
# Предполагается, что database.py находится в той же директории
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

# --- Утилиты безопасности ---

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

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

# --- Настройка базы данных ---

@app.on_event("startup")
async def startup():
    print("Connecting to the database...")
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    print("Disconnecting from the database...")
    await database.disconnect()

# --- Schemas ---

class UserIn(BaseModel):
    email: EmailStr
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
    address: Optional[str]
    visit_date: Optional[datetime]
    is_premium: bool

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
    is_premium: bool

class ToolRequestIn(BaseModel):
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

# ИСПРАВЛЕННАЯ СХЕМА: rental_start_date и rental_end_date теперь Optional[date], 
# чтобы обработать NULL из базы данных, что устраняет ошибку 422.
class ToolRequestOut(BaseModel):
    id: int
    user_id: int
    tool_name: str
    description: Optional[str]
    rental_price: float
    tool_count: int
    rental_start_date: Optional[date] 
    rental_end_date: Optional[date]   
    contact_info: str
    has_delivery: bool
    delivery_address: Optional[str]
    city_id: int
    created_at: datetime

class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str]
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
    is_premium: bool

class SpecializationUpdate(BaseModel):
    specialization: str

class CityOut(BaseModel):
    id: int
    name: str

class ChatMessageIn(BaseModel):
    message: str

class ChatMessageOut(BaseModel):
    id: int
    sender_id: int
    sender_username: str
    message: str
    timestamp: datetime

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ОЧИСТКИ ДАННЫХ (FIX для 422 и чата) ---

def clean_requests_list(requests):
    """Очищает список записей от NULL-значений для полей Boolean и других, которые Pydantic ожидает."""
    cleaned_requests = []
    for req in requests:
        # Pydantic RowProxy/Record в словарь
        req_dict = dict(req)
        
        # 1. Очистка is_premium (для всех premium-таблиц)
        if "is_premium" in req_dict and req_dict.get("is_premium") is None:
            req_dict["is_premium"] = False
            
        # 2. Очистка work_requests специфичных полей
        if "is_taken" in req_dict and req_dict.get("is_taken") is None:
            req_dict["is_taken"] = False
        if "chat_enabled" in req_dict and req_dict.get("chat_enabled") is None:
            req_dict["chat_enabled"] = False
            
        # 3. Очистка has_delivery (для tool_requests)
        if "has_delivery" in req_dict and req_dict.get("has_delivery") is None:
             req_dict["has_delivery"] = False
            
        cleaned_requests.append(req_dict)
    return cleaned_requests

def clean_single_request(request_item):
    """Очищает одну запись от NULL-значений."""
    if not request_item:
        return None
        
    req_dict = dict(request_item)
    # 1. Очистка is_premium
    if "is_premium" in req_dict and req_dict.get("is_premium") is None:
        req_dict["is_premium"] = False
    # 2. Очистка work_requests специфичных полей
    if "is_taken" in req_dict and req_dict.get("is_taken") is None:
        req_dict["is_taken"] = False
    if "chat_enabled" in req_dict and req_dict.get("chat_enabled") is None:
        req_dict["chat_enabled"] = False
    # 3. Очистка has_delivery
    if "has_delivery" in req_dict and req_dict.get("has_delivery") is None:
             req_dict["has_delivery"] = False
    
    return req_dict
# --- КОНЕЦ ВСПОМОГАТЕЛЬНЫХ ФУНКЦИЙ ---


# --- API endpoints ---

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
    access_token = create_access_token(
        data={"sub": str(user["id"])}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.post("/register", response_model=UserOut)
async def create_user(user: UserIn):
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
    
    # Очистка is_premium для UserOut
    user_dict = clean_single_request(created_user)
    user_dict["username"] = user_dict["email"]
    return user_dict


@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    # Очистка is_premium для UserOut
    user_dict = clean_single_request(current_user)
    user_dict["username"] = user_dict["email"]
    return user_dict

@api_router.put("/users/update-specialization")
async def update_specialization(specialization_update: SpecializationUpdate, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только ИСПОЛНИТЕЛЬ может обновлять специализацию")
    
    query = users.update().where(users.c.id == current_user["id"]).values(specialization=specialization_update.specialization)
    await database.execute(query)
    return {"message": "Специализация успешно обновлена"}

@api_router.post("/subscribe")
async def subscribe(current_user: dict = Depends(get_current_user)):
    query = users.update().where(users.c.id == current_user["id"]).values(is_premium=True)
    await database.execute(query)
    return {"message": "Премиум-подписка успешно активирована!"}

@api_router.get("/cities/")
async def get_cities():
    query = cities.select()
    return await database.fetch_all(query)

# --- СПИСКИ ДЛЯ ФРОНТЕНДА ---

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
    return SPECIALIZATIONS_LIST

@api_router.get("/machinery_types/")
def get_machinery_types():
    return MACHINERY_TYPES

@api_router.get("/tools_list/")
def get_tools_list():
    return TOOLS_LIST

@api_router.get("/material_types/")
def get_material_types():
    return MATERIAL_TYPES

# --- Work Requests ---

@api_router.post("/work_requests", response_model=WorkRequestOut, status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК может создавать заявки на работу")
    
    query = work_requests.insert().values(
        user_id=current_user["id"],
        name=request.name,
        description=request.description,
        specialization=request.specialization,
        budget=request.budget,
        phone_number=request.phone_number,
        city_id=request.city_id,
        address=request.address,
        visit_date=request.visit_date,
        is_premium=current_user["is_premium"],
        is_taken=False,
        chat_enabled=False
    )
    last_record_id = await database.execute(query)
    created_request_query = work_requests.select().where(work_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    
    if created_request:
        return clean_single_request(created_request)
    raise HTTPException(status_code=500, detail="Не удалось получить созданную заявку.")


@api_router.get("/work_requests/{city_id}", response_model=List[WorkRequestOut])
async def get_work_requests(city_id: int, current_user: dict = Depends(get_current_user)):
    query = work_requests.select().where((work_requests.c.city_id == city_id))
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)

@api_router.get("/work_requests/my", response_model=List[WorkRequestOut])
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    query = work_requests.select().where(work_requests.c.user_id == current_user["id"])
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)
    
@api_router.get("/work_requests/taken", response_model=List[WorkRequestOut])
async def get_my_taken_work_requests(current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        return []
    query = work_requests.select().where(work_requests.c.executor_id == current_user["id"])
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)


@api_router.post("/work_requests/{request_id}/take", status_code=status.HTTP_200_OK)
async def take_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
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

# --- Chat Endpoints (ИСПРАВЛЕНО) ---

@api_router.get("/work_requests/{request_id}/chat", response_model=List[ChatMessageOut])
async def get_chat_messages(request_id: int, current_user: dict = Depends(get_current_user)):
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_item = await database.fetch_one(request_query)

    if not request_item:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    # 🔥 ФИКС: Очищаем запрос, чтобы chat_enabled не был None, если он не был обновлен.
    request_item = clean_single_request(request_item)

    is_owner = request_item["user_id"] == current_user["id"]
    is_executor = request_item["executor_id"] == current_user["id"]

    if not (is_owner or is_executor):
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому чату")
    
    # Теперь эта проверка гарантированно сработает с False, а не с None.
    if not request_item["chat_enabled"]:
        raise HTTPException(status_code=400, detail="Чат для этой заявки не активирован")

    query = """
    SELECT cm.id, cm.sender_id, cm.message, cm.timestamp, u.email as sender_username
    FROM chat_messages cm
    JOIN users u ON cm.sender_id = u.id
    WHERE cm.request_id = :request_id
    ORDER BY cm.timestamp
    """
    messages = await database.fetch_all(query, values={"request_id": request_id})
    return messages

@api_router.post("/work_requests/{request_id}/chat", status_code=status.HTTP_201_CREATED)
async def send_chat_message(request_id: int, message: ChatMessageIn, current_user: dict = Depends(get_current_user)):
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_item = await database.fetch_one(request_query)

    if not request_item:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    # 🔥 ФИКС: Очищаем запрос, чтобы chat_enabled не был None, если он не был обновлен.
    request_item = clean_single_request(request_item)

    is_owner = request_item["user_id"] == current_user["id"]
    is_executor = request_item["executor_id"] == current_user["id"]

    if not (is_owner or is_executor):
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому чату")

    # Теперь эта проверка гарантированно сработает с False, а не с None.
    if not request_item["chat_enabled"]:
        raise HTTPException(status_code=400, detail="Чат для этой заявки не активирован")

    query = chat_messages.insert().values(
        request_id=request_id,
        sender_id=current_user["id"],
        message=message.message
    )
    await database.execute(query)
    
    return {"message": "Сообщение отправлено"}

# --- Machinery Requests ---

@api_router.post("/machinery_requests", response_model=MachineryRequestOut, status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
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
    
    if created_request:
        return clean_single_request(created_request)
    raise HTTPException(status_code=500, detail="Не удалось получить созданную заявку.")


@api_router.get("/machinery_requests/{city_id}", response_model=List[MachineryRequestOut])
async def get_machinery_requests(city_id: int, current_user: dict = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)

@api_router.get("/machinery_requests/my", response_model=List[MachineryRequestOut])
async def get_my_machinery_requests(current_user: dict = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.user_id == current_user["id"])
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)

# --- Tool Requests --- 

@api_router.post("/tool_requests", response_model=ToolRequestOut, status_code=status.HTTP_201_CREATED)
async def create_tool_request(request: ToolRequestIn, current_user: dict = Depends(get_current_user)):
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
    
    if created_request:
        return clean_single_request(created_request)
    raise HTTPException(status_code=500, detail="Не удалось получить созданную заявку.")

@api_router.get("/tool_requests/{city_id}", response_model=List[ToolRequestOut])
async def get_tool_requests(city_id: int, current_user: dict = Depends(get_current_user)):
    query = tool_requests.select().where(tool_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)

@api_router.get("/tool_requests/my", response_model=List[ToolRequestOut])
async def get_my_tool_requests(current_user: dict = Depends(get_current_user)):
    query = tool_requests.select().where(tool_requests.c.user_id == current_user["id"])
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)


# --- Material Ads ---

@api_router.post("/material_ads", response_model=MaterialAdOut, status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
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
    
    if created_ad:
        return clean_single_request(created_ad)
    raise HTTPException(status_code=500, detail="Не удалось получить созданное объявление.")


@api_router.get("/material_ads/{city_id}", response_model=List[MaterialAdOut])
async def get_material_ads(city_id: int, current_user: dict = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)

@api_router.get("/material_ads/my", response_model=List[MaterialAdOut])
async def get_my_material_ads(current_user: dict = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.user_id == current_user["id"])
    requests = await database.fetch_all(query)
    return clean_requests_list(requests)

# --- Static Files Mounting ---

app.include_router(api_router)

# Обслуживание статических файлов и главной страницы
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")

    @app.get("/")
    async def read_index():
        return FileResponse(static_path / "index.html")
else:
    print(f"Warning: Static directory not found at {static_path}")