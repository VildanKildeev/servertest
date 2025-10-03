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
from typing import Optional, List, Dict
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import exc, select
from sqlalchemy.orm import relationship
import os
from dotenv import load_dotenv
from pathlib import Path
from database import metadata, engine
from fastapi import WebSocket, WebSocketDisconnect # Новые импорты
from fastapi import Query # Новый импорт
from sqlalchemy import select, or_, and_ # Обновите для более сложного запроса

# --- Database setup ---
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities, database, chat_messages, work_request_offers

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
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
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


async def is_email_taken(email: str) -> bool:
    query = users.select().where(users.c.email == email)
    user = await database.fetch_one(query)
    return user is not None


@app.on_event("startup")
async def startup():
    # --- ДОБАВЬТЕ ЭТИ ДВЕ СТРОКИ ---
    # Эта команда создает все таблицы, описанные в database.py, если их еще нет.
    # Она безопасна для повторного запуска.
    metadata.create_all(engine)
    # ------------------------------------
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
    phone_number: str # Будет скрываться на бэкенде для не-премиум
    city_id: int
    created_at: datetime
    is_taken: bool
    address: Optional[str]
    visit_date: Optional[datetime]
    is_premium: Optional[bool]


# --- OFFER SCHEMAS ---
class OfferOut(BaseModel):
    id: int
    request_id: int
    performer_id: int
    timestamp: datetime
    status: str
    performer: UserOut # Вложенная информация об исполнителе

# --- MACHINERY REQUESTS SCHEMAS ---
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
    is_premium: Optional[bool]


# --- TOOL REQUESTS SCHEMAS ---
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

class ToolRequestOut(BaseModel):
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
    is_premium: Optional[bool]


# --- UTILITY SCHEMAS ---
class SpecializationUpdate(BaseModel):
    specialization: str

class CityOut(BaseModel):
    id: int
    name: str

# Определите ConnectionManager сразу после импортов и настроек
class ConnectionManager:
    """Управляет активными WebSocket-соединениями по request_id."""
    def __init__(self):
        # Словарь: {request_id: [WebSocket, WebSocket, ...]}
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, request_id: int):
        await websocket.accept()
        if request_id not in self.active_connections:
            self.active_connections[request_id] = []
        self.active_connections[request_id].append(websocket)
        # Опциональный вывод в лог
        # print(f"WS: Пользователь подключен к чату {request_id}")

    def disconnect(self, websocket: WebSocket, request_id: int):
        if request_id in self.active_connections and websocket in self.active_connections[request_id]:
            self.active_connections[request_id].remove(websocket)
            if not self.active_connections[request_id]:
                del self.active_connections[request_id]
        # print(f"WS: Пользователь отключен от чата {request_id}")

    async def broadcast(self, request_id: int, message: str):
        """Отправляет сообщение всем участникам чата по данному request_id."""
        if request_id in self.active_connections:
            for connection in self.active_connections[request_id]:
                await connection.send_text(message)

manager = ConnectionManager()

class ChatMessageIn(BaseModel):
    message: str

class ChatMessageOut(BaseModel):
    id: int
    request_id: int
    sender_id: int
    recipient_id: int
    sender_username: str
    message: str
    timestamp: datetime

class RatingIn(BaseModel):
    rating_value: int = Field(..., ge=1, le=5)

class ChatSummary(BaseModel):
    """Модель для отображения активного диалога в списке."""
    request_id: int
    opponent_id: int
    opponent_name: str
    last_message: Optional[str]
    is_work_request_owner: bool # Полезно для логики фронтенда

# ----------------------------------------------------
# --- API endpoints ---
# ----------------------------------------------------

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
        is_premium=False,
        rating=0.0,
        rating_count=0
    )
    
    last_record_id = await database.execute(query)
    created_user_query = users.select().where(users.c.id == last_record_id)
    created_user = await database.fetch_one(created_user_query)
    
    return created_user

@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user

@api_router.post("/work_requests/{request_id}/rate")
async def rate_executor(request_id: int, rating: RatingIn, current_user: dict = Depends(get_current_user)):
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

@api_router.get("/chats/my_active_chats", response_model=List[ChatSummary])
async def get_my_active_chats(current_user: dict = Depends(get_current_user)):
    """Получает список всех уникальных диалогов, в которых участвует пользователь."""
    user_id = current_user["id"]
    
    # 1. Запрос для поиска всех уникальных request_id и собеседников
    # Используем Union для объединения запросов, где пользователь — отправитель ИЛИ получатель.
    # Это позволяет найти все уникальные пары (request_id, opponent_id).
    
    # Запрос на все сообщения, где пользователь - отправитель
    q1 = select(chat_messages.c.request_id, chat_messages.c.recipient_id.label("opponent_id")) \
         .where(chat_messages.c.sender_id == user_id)
    
    # Запрос на все сообщения, где пользователь - получатель
    q2 = select([chat_messages.c.request_id, chat_messages.c.sender_id.label("opponent_id")]) \
         .where(chat_messages.c.recipient_id == user_id)

    # Объединяем, группируем, чтобы получить уникальные диалоги
    union_query = q1.union(q2).alias("unique_dialogs")
    final_query = select([union_query.c.request_id, union_query.c.opponent_id]).distinct()
    
    chat_participants = await database.fetch_all(final_query)

    result = []
    
    for dialog in chat_participants:
        opponent_id = dialog["opponent_id"]
        request_id = dialog["request_id"]
        
        # Получаем имя собеседника
        opponent = await database.fetch_one(select([users.c.email]).where(users.c.id == opponent_id))
        opponent_name = opponent["email"].split("@")[0] if opponent else f"Пользователь #{opponent_id}"
        
        # Получаем последнее сообщение для отображения в списке
        last_message_query = chat_messages.select().where(
            and_(
                chat_messages.c.request_id == request_id,
                or_(
                    and_(chat_messages.c.sender_id == user_id, chat_messages.c.recipient_id == opponent_id),
                    and_(chat_messages.c.sender_id == opponent_id, chat_messages.c.recipient_id == user_id)
                )
            )
        ).order_by(chat_messages.c.id.desc()).limit(1)
        
        last_message_record = await database.fetch_one(last_message_query)
        last_message = last_message_record["message"] if last_message_record else "Начать диалог"
        
        # Проверяем, является ли пользователь владельцем заявки
        work_request = await database.fetch_one(select([work_requests.c.user_id]).where(work_requests.c.id == request_id))
        is_owner = work_request["user_id"] == user_id if work_request else False

        result.append(ChatSummary(
            request_id=request_id,
            opponent_id=opponent_id,
            opponent_name=opponent_name,
            last_message=last_message,
            is_work_request_owner=is_owner
        ))

    return result

@api_router.put("/users/update-specialization")
async def update_specialization(specialization_update: SpecializationUpdate, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только ИСПОЛНИТЕЛЬ может обновлять специализацию")
    
    query = users.update().where(users.c.id == current_user["id"]).values(specialization=specialization_update.specialization)
    await database.execute(query)
    return {"message": "Специализация успешно обновлена"}

# main.py (В разделе @api_router)
@api_router.websocket("/ws/chat/{request_id}/{opponent_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    request_id: int, 
    opponent_id: int,
    token: str = Query(...) # Токен для аутентификации
):
    """
    Эндпоинт для WebSocket-подключения. 
    request_id - ID заявки, opponent_id - ID собеседника.
    """
    try:
        # Аутентификация пользователя по токену
        user = await get_current_user(token)
        user_id = user["id"]
        username = user["email"].split("@")[0] # Имя пользователя
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    await manager.connect(websocket, request_id)
    
    try:
        while True:
            # Получаем сообщение от пользователя
            data = await websocket.receive_text()
            
            # --- Сохранение сообщения в базу данных ---
            # Сохраняем сообщение с явным указанием отправителя и получателя
            query = chat_messages.insert().values(
                request_id=request_id,
                sender_id=user_id,
                recipient_id=opponent_id, # Получатель известен из URL
                message=data,
                created_at=datetime.utcnow()
            )
            await database.execute(query)
            
            # --- Отправка сообщения всем подключенным (broadcast) ---
            # Сообщение в формате JSON, чтобы фронтенд мог определить, кто отправитель
            message_payload = json.dumps({
                "sender_id": user_id,
                "sender_name": username,
                "message": data,
                "time": datetime.utcnow().strftime("%H:%M")
            })
            
            await manager.broadcast(request_id, message_payload)

    except WebSocketDisconnect:
        manager.disconnect(websocket, request_id)
    except Exception as e:
        # print(f"WS Error in chat {request_id}: {e}")
        manager.disconnect(websocket, request_id)
        # Опционально: отправить сообщение об ошибке клиенту

@api_router.post("/subscribe")
async def subscribe(current_user: dict = Depends(get_current_user)):
    query = users.update().where(users.c.id == current_user["id"]).values(is_premium=True)
    await database.execute(query)
    return {"message": "Премиум-подписка успешно активирована!"}


@api_router.get("/cities/")
async def get_cities():
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
MACHINERY_TYPES = ["Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Трактор", "Манипулятор", "Бетононасос", "Ямобур", "Каток", "Фронтальный погрузчик", "Грейдер", "Эвакуатор", "Мини-погрузчик"]
TOOLS_LIST = ["Бетономешалка", "Виброплита", "Генератор", "Компрессор", "Отбойный молоток", "Перфоратор", "Лазерный нивелир", "Бензопила", "Сварочный аппарат", "Шуруповерт", "Болгарка", "Строительный пылесос", "Тепловая пушка", "Мотобур", "Вибратор для бетона", "Рубанок", "Лобзик", "Торцовочная пила", "Краскопульт", "Штроборез", "Резчик швов", "Резчик кровли", "Шлифовальная машина", "Промышленный фен", "Домкрат", "Лебедка", "Плиткорез", "Камнерезный станок", "Отрезной станок", "Гидравлическая тележка", "Парогенератор", "Бытовка", "Кран Пионер", "Кран Умелец"]
MATERIAL_TYPES = ["Цемент", "Песок", "Щебень", "Кирпич", "Бетон", "Армирующие материалы", "Гипсокартон", "Штукатурка", "Шпаклевка", "Краски", "Клей", "Грунтовка", "Плитка", "Линолеум", "Ламинат", "Паркет", "Фанера", "ОСБ", "Металлочерепица", "Профнастил", "Утеплитель", "Монтажная пена", "Деревянные брусья/доски"]

@api_router.get("/specializations/")
def get_specializations(): return SPECIALIZATIONS_LIST
@api_router.get("/machinery_types/")
def get_machinery_types(): return MACHINERY_TYPES
@api_router.get("/tools_list/")
def get_tools_list(): return TOOLS_LIST
@api_router.get("/material_types/")
def get_material_types(): return MATERIAL_TYPES


# ----------------------------------------------------
# --- Work Requests Endpoints ---
# ----------------------------------------------------

@api_router.post("/work_requests", response_model=WorkRequestOut, status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК может создавать заявки на работу")

    visit_date_data = request.visit_date
    if visit_date_data and visit_date_data.tzinfo is not None:
        visit_date_data = visit_date_data.replace(tzinfo=None)

    query = work_requests.insert().values(
        user_id=current_user["id"], name=request.name, description=request.description,
        specialization=request.specialization, budget=request.budget, phone_number=request.phone_number,
        city_id=request.city_id, address=request.address, visit_date=visit_date_data,
        is_premium=current_user["is_premium"], is_taken=False
    )
    last_record_id = await database.execute(query)
    created_request_query = work_requests.select().where(work_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    return created_request

@api_router.get("/work_requests/by_city/{city_id}", response_model=List[WorkRequestOut])
async def get_work_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    query = work_requests.select().where((work_requests.c.city_id == city_id))
    results = await database.fetch_all(query)
    
    # Скрываем номер телефона для не-премиум пользователей
    response_data = []
    for r in results:
        request_data = dict(r)
        if not current_user["is_premium"]:
            request_data["phone_number"] = "Доступно премиум-исполнителям"
        response_data.append(request_data)
        
    return response_data

@api_router.get("/work_requests/my", response_model=List[WorkRequestOut])
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    query = work_requests.select().where(work_requests.c.user_id == current_user["id"])
    return await database.fetch_all(query)
    
@api_router.get("/work_requests/taken", response_model=List[WorkRequestOut])
async def get_my_taken_work_requests(current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        return []
    query = work_requests.select().where(work_requests.c.executor_id == current_user["id"])
    return await database.fetch_all(query)

# --- НОВЫЕ ЭНДПОИНТЫ ДЛЯ СИСТЕМЫ ПРЕДЛОЖЕНИЙ ---

@api_router.post("/work_requests/{request_id}/offer", status_code=status.HTTP_201_CREATED)
async def make_offer_for_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только ИСПОЛНИТЕЛЬ может предлагать услуги")

    async with database.transaction():
        request_query = work_requests.select().where(work_requests.c.id == request_id)
        request_item = await database.fetch_one(request_query)
        if not request_item:
            raise HTTPException(status_code=404, detail="Заявка не найдена")
        if request_item["is_taken"]:
            raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем")
        if request_item["user_id"] == current_user["id"]:
            raise HTTPException(status_code=400, detail="Вы не можете откликнуться на свою же заявку")

        existing_offer_query = work_request_offers.select().where(
            (work_request_offers.c.request_id == request_id) & (work_request_offers.c.performer_id == current_user["id"])
        )
        existing_offer = await database.fetch_one(existing_offer_query)
        if existing_offer:
            raise HTTPException(status_code=409, detail="Вы уже откликнулись на эту заявку")

        insert_query = work_request_offers.insert().values(request_id=request_id, performer_id=current_user["id"])
        await database.execute(insert_query)

    return {"message": "Вы успешно откликнулись на заявку. Заказчик сможет начать с вами чат."}

@api_router.get("/work_requests/{request_id}/offers", response_model=List[OfferOut])
async def get_offers_for_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_item = await database.fetch_one(request_query)
    if not request_item or request_item["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    query = select([work_request_offers, users]).where(
        work_request_offers.c.request_id == request_id
    ).select_from(work_request_offers.join(users, work_request_offers.c.performer_id == users.c.id))
    
    offers = await database.fetch_all(query)

    return [
        {
            "id": offer["id"], "request_id": offer["request_id"], "performer_id": offer["performer_id"],
            "timestamp": offer["timestamp"], "status": offer["status"],
            "performer": {**offer, "hashed_password": None} # Возвращаем полную инфу об исполнителе
        }
        for offer in offers
    ]

@api_router.post("/work_requests/offers/{offer_id}/accept", status_code=status.HTTP_200_OK)
async def accept_offer(offer_id: int, current_user: dict = Depends(get_current_user)):
    async with database.transaction():
        offer_query = work_request_offers.select().where(work_request_offers.c.id == offer_id)
        offer = await database.fetch_one(offer_query)
        if not offer:
            raise HTTPException(status_code=404, detail="Предложение не найдено")

        request_query = work_requests.select().where(work_requests.c.id == offer["request_id"])
        request_item = await database.fetch_one(request_query)
        if not request_item or request_item["user_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Доступ запрещен")
        if request_item["is_taken"]:
            raise HTTPException(status_code=400, detail="Исполнитель для этой заявки уже выбран")

        # 1. Обновляем заявку
        update_request_query = work_requests.update().where(work_requests.c.id == offer["request_id"]).values(
            is_taken=True, executor_id=offer["performer_id"]
        )
        await database.execute(update_request_query)

        # 2. Принимаем это предложение
        update_offer_query = work_request_offers.update().where(work_request_offers.c.id == offer_id).values(status="accepted")
        await database.execute(update_offer_query)

        # 3. Отклоняем все остальные
        reject_others_query = work_request_offers.update().where(
            (work_request_offers.c.request_id == offer["request_id"]) & (work_request_offers.c.id != offer_id)
        ).values(status="rejected")
        await database.execute(reject_others_query)
    
    return {"message": "Исполнитель успешно выбран!"}

# ----------------------------------------------------
# --- Chat Endpoints ---
# ----------------------------------------------------

@api_router.get("/work_requests/{request_id}/chat/{participant_id}", response_model=List[ChatMessageOut])
async def get_chat_messages(request_id: int, participant_id: int, current_user: dict = Depends(get_current_user)):
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_item = await database.fetch_one(request_query)
    if not request_item:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    is_customer = request_item["user_id"] == current_user["id"] and participant_id != current_user["id"]
    is_performer = current_user["id"] == participant_id and request_item["user_id"] != current_user["id"]

    if not (is_customer or is_performer):
        raise HTTPException(status_code=403, detail="У вас нет доступа к этому чату")

    # Проверяем, что исполнитель откликнулся на заявку
    if is_performer:
        offer_query = work_request_offers.select().where(
            (work_request_offers.c.request_id == request_id) & (work_request_offers.c.performer_id == current_user["id"])
        )
        if not await database.fetch_one(offer_query):
            raise HTTPException(status_code=403, detail="Вы должны откликнуться на заявку, чтобы начать чат")

    customer_id = request_item["user_id"]
    
    query = """
    SELECT cm.id, cm.request_id, cm.sender_id, cm.recipient_id, cm.message, cm.timestamp, u.email as sender_username
    FROM chat_messages cm JOIN users u ON cm.sender_id = u.id
    WHERE cm.request_id = :request_id AND 
          ((cm.sender_id = :user1_id AND cm.recipient_id = :user2_id) OR 
           (cm.sender_id = :user2_id AND cm.recipient_id = :user1_id))
    ORDER BY cm.timestamp
    """
    messages = await database.fetch_all(query, values={
        "request_id": request_id,
        "user1_id": customer_id,
        "user2_id": participant_id
    })
    return messages


@api_router.post("/work_requests/{request_id}/chat/{recipient_id}", status_code=status.HTTP_201_CREATED)
async def send_chat_message(request_id: int, recipient_id: int, message: ChatMessageIn, current_user: dict = Depends(get_current_user)):
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_item = await database.fetch_one(request_query)
    if not request_item:
        raise HTTPException(status_code=404, detail="Заявка не найдена")

    # Проверяем, что чат легитимен (между заказчиком и откликнувшимся исполнителем)
    is_sender_customer = request_item["user_id"] == current_user["id"]
    is_sender_performer = recipient_id == request_item["user_id"]

    if not (is_sender_customer or is_sender_performer):
         raise HTTPException(status_code=403, detail="У вас нет доступа к этому чату")

    # Исполнитель может писать только если он откликнулся
    if is_sender_performer:
        offer_query = work_request_offers.select().where(
            (work_request_offers.c.request_id == request_id) & (work_request_offers.c.performer_id == current_user["id"])
        )
        if not await database.fetch_one(offer_query):
            raise HTTPException(status_code=403, detail="Вы должны откликнуться на заявку, чтобы начать чат")

    query = chat_messages.insert().values(
        request_id=request_id,
        sender_id=current_user["id"],
        recipient_id=recipient_id,
        message=message.message
    )
    await database.execute(query)
    
    return {"message": "Сообщение отправлено"}

# ----------------------------------------------------
# --- Machinery, Tool, Material Endpoints (без изменений) ---
# ----------------------------------------------------

@api_router.post("/machinery_requests", response_model=MachineryRequestOut, status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        user_id=current_user["id"], machinery_type=request.machinery_type, description=request.description,
        rental_date=request.rental_date, min_hours=request.min_hours, rental_price=request.rental_price,
        contact_info=request.contact_info, city_id=request.city_id, is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    created_request_query = machinery_requests.select().where(machinery_requests.c.id == last_record_id)
    return await database.fetch_one(created_request_query)

@api_router.get("/machinery_requests/by_city/{city_id}", response_model=List[MachineryRequestOut])
async def get_machinery_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.city_id == city_id)
    return await database.fetch_all(query)

@api_router.get("/machinery_requests/my", response_model=List[MachineryRequestOut])
async def get_my_machinery_requests(current_user: dict = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.user_id == current_user["id"])
    return await database.fetch_all(query)

@api_router.post("/tool_requests", response_model=ToolRequestOut, status_code=status.HTTP_201_CREATED)
async def create_tool_request(request: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    query = tool_requests.insert().values(
        user_id=current_user["id"], tool_name=request.tool_name, description=request.description,
        rental_price=request.rental_price, tool_count=request.tool_count, rental_start_date=request.rental_start_date,
        rental_end_date=request.rental_end_date, contact_info=request.contact_info, has_delivery=request.has_delivery,
        delivery_address=request.delivery_address, city_id=request.city_id
    )
    last_record_id = await database.execute(query)
    created_request_query = tool_requests.select().where(tool_requests.c.id == last_record_id)
    return await database.fetch_one(created_request_query)

@api_router.get("/tool_requests/by_city/{city_id}", response_model=List[ToolRequestOut])
async def get_tool_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    query = tool_requests.select().where(tool_requests.c.city_id == city_id)
    return await database.fetch_all(query)

@api_router.get("/tool_requests/my", response_model=List[ToolRequestOut])
async def get_my_tool_requests(current_user: dict = Depends(get_current_user)):
    query = tool_requests.select().where(tool_requests.c.user_id == current_user["id"])
    return await database.fetch_all(query)

@api_router.post("/material_ads", response_model=MaterialAdOut, status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    query = material_ads.insert().values(
        user_id=current_user["id"], material_type=ad.material_type, description=ad.description,
        price=ad.price, contact_info=ad.contact_info, city_id=ad.city_id, is_premium=current_user["is_premium"]
    )
    last_record_id = await database.execute(query)
    created_ad_query = material_ads.select().where(material_ads.c.id == last_record_id)
    return await database.fetch_one(created_ad_query)

@api_router.get("/material_ads/by_city/{city_id}", response_model=List[MaterialAdOut])
async def get_material_ads_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.city_id == city_id)
    return await database.fetch_all(query)

@api_router.get("/material_ads/my", response_model=List[MaterialAdOut])
async def get_my_material_ads(current_user: dict = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.user_id == current_user["id"])
    return await database.fetch_all(query)

# ----------------------------------------------------
# --- Static Files Mounting ---
# ----------------------------------------------------
app.include_router(api_router)

static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")
    @app.get("/")
    async def read_index():
        return FileResponse(static_path / "index.html")