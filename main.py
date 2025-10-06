import json
import uvicorn
import databases
import asyncpg
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import exc, select, or_, and_
import os
from dotenv import load_dotenv
from pathlib import Path

# --- Database setup ---
from database import (
    metadata, engine, users, work_requests, machinery_requests, 
    tool_requests, material_ads, cities, database, chat_messages, 
    work_request_offers
)

load_dotenv()

# --- Security and App Settings ---
SECRET_KEY = os.environ.get("SECRET_KEY", "a-secure-default-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 часа

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="СМЗ.РФ API")
api_router = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, request_id: int):
        await websocket.accept()
        if request_id not in self.active_connections:
            self.active_connections[request_id] = []
        self.active_connections[request_id].append(websocket)

    def disconnect(self, websocket: WebSocket, request_id: int):
        if request_id in self.active_connections and websocket in self.active_connections[request_id]:
            self.active_connections[request_id].remove(websocket)
            if not self.active_connections[request_id]:
                del self.active_connections[request_id]

    async def broadcast(self, request_id: int, message: str):
        if request_id in self.active_connections:
            for connection in self.active_connections[request_id]:
                await connection.send_text(message)

manager = ConnectionManager()

# --- Pydantic Schemas ---

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
    phone_number: Optional[str] = None
    is_active: bool
    created_at: datetime
    city_id: int
    specialization: Optional[str] = None
    is_premium: bool
    user_type: str
    rating: Optional[float] = Field(0.0, description="Рейтинг пользователя")
    rating_count: Optional[int] = Field(0, description="Количество оценок")
    
    class Config:
        from_attributes = True

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
    address: Optional[str]
    visit_date: Optional[datetime]
    is_premium: bool

class OfferOut(BaseModel):
    id: int
    request_id: int
    performer_id: int
    timestamp: datetime
    status: str
    performer: UserOut

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
    min_hours: int
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
    request_id: int
    opponent_id: int
    opponent_name: str
    last_message: Optional[str]
    
# --- Utility Functions ---

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception
    
    user = await database.fetch_one(users.select().where(users.c.id == user_id))
    if user is None:
        raise credentials_exception
    return user

# --- App Lifecycle Events ---

@app.on_event("startup")
async def startup():
    # ИСПРАВЛЕНО: Добавлена команда для создания таблиц в БД, если их нет.
    metadata.create_all(engine)
    print("Connecting to the database...")
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    print("Disconnecting from the database...")
    await database.disconnect()

# --- API Endpoints ---

# --- Authentication and Users ---

@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await database.fetch_one(users.select().where(users.c.email == form_data.username))
    
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
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

    if await database.fetch_one(users.select().where(users.c.email == user.email)):
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует.")

    if user.user_type == "ИСПОЛНИТЕЛЬ" and not user.specialization:
        raise HTTPException(status_code=400, detail="Для типа 'ИСПОЛНИТЕЛЬ' поле 'specialization' обязательно.")

    query = users.insert().values(
        email=user.email,
        hashed_password=get_password_hash(user.password),
        user_type=user.user_type,
        phone_number=user.phone_number,
        specialization=user.specialization if user.user_type == "ИСПОЛНИТЕЛЬ" else None,
        city_id=user.city_id,
    )
    
    last_record_id = await database.execute(query)
    return await database.fetch_one(users.select().where(users.c.id == last_record_id))

@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user

# --- Lists for Frontend ---
SPECIALIZATIONS_LIST = [ "ЗЕМЛЯНЫЕ РАБОТЫ", "ФУНДАМЕНТЫ И ОСНОВАНИЯ", "КЛАДОЧНЫЕ РАБОТЫ", "МЕТАЛЛОКОНСТРУКЦИИ", "КРОВЕЛЬНЫЕ РАБОТЫ", "ОСТЕКЛЕНИЕ И ФАСАДНЫЕ РАБОТЫ", "ВНУТРЕННИЕ ИНЖЕНЕРНЫЕ СЕТИ", "САНТЕХНИЧЕСКИЕ И ВОДОПРОВОДНЫЕ РАБОТЫ", "ОТОПЛЕНИЕ И ТЕПЛОСНАБЖЕНИЕ", "ВЕНТИЛЯЦИЯ И КОНДИЦИОНИРОВАНИЕ", "ЭЛЕКТРОМОНТАЖНЫЕ РАБОТЫ", "ОТДЕЛОЧНЫЕ РАБОТЫ", "МОНТАЖ ПОТОЛКОВ", "ПОЛУСУХАЯ СТЯЖКА ПОЛА", "МАЛЯРНЫЕ РАБОТЫ", "БЛАГОУСТРОЙСТВО ТЕРРИТОРИИ", "СТРОИТЕЛЬСТВО ДОМОВ ПОД КЛЮЧ", "ДЕМОНТАЖНЫЕ РАБОТЫ", "МОНТАЖ ОБОРУДОВАНИЯ", "РАЗНОРАБОЧИЕ", "КЛИНИНГ, УБОРКА ПОМЕЩЕНИЙ", "МУЖ НА ЧАС", "БУРЕНИЕ, УСТРОЙСТВО СКВАЖИН", "ПРОЕКТИРОВАНИЕ", "ГЕОЛОГИЯ" ]
MACHINERY_TYPES = [ "Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Трактор", "Манипулятор", "Бетононасос", "Ямобур", "Каток", "Фронтальный погрузчик", "Грейдер", "Эвакуатор", "Мини-погрузчик" ]
TOOLS_LIST = [ "Бетономешалка", "Виброплита", "Генератор", "Компрессор", "Отбойный молоток", "Перфоратор", "Лазерный нивелир", "Бензопила", "Сварочный аппарат", "Шуруповерт", "Болгарка", "Строительный пылесос", "Тепловая пушка", "Мотобур", "Вибратор для бетона", "Рубанок", "Лобзик", "Торцовочная пила", "Краскопульт", "Штроборез", "Резчик швов", "Резчик кровли", "Шлифовальная машина", "Промышленный фен", "Домкрат", "Лебедка", "Плиткорез", "Камнерезный станок", "Отрезной станок", "Гидравлическая тележка", "Парогенератор", "Бытовка", "Кран Пионер", "Кран Умелец" ]
MATERIAL_TYPES = [ "Цемент", "Песок", "Щебень", "Кирпич", "Бетон", "Армирующие материалы", "Гипсокартон", "Штукатурка", "Шпаклевка", "Краски", "Клей", "Грунтовка", "Плитка", "Линолеум", "Ламинат", "Паркет", "Фанера", "ОСБ", "Металлочерепица", "Профнастил", "Утеплитель", "Монтажная пена", "Деревянные брусья/доски" ]

@api_router.get("/specializations/")
def get_specializations(): return SPECIALIZATIONS_LIST
@api_router.get("/machinery_types/")
def get_machinery_types(): return MACHINERY_TYPES
@api_router.get("/tools_list/")
def get_tools_list(): return TOOLS_LIST
@api_router.get("/material_types/")
def get_material_types(): return MATERIAL_TYPES
@api_router.get("/cities/")
async def get_cities():
    return await database.fetch_all(cities.select())

# --- Work Requests ---

@api_router.post("/work_requests", response_model=WorkRequestOut, status_code=status.HTTP_201_CREATED)
async def create_work_request(request_data: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ЗАКАЗЧИК":
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК может создавать заявки.")

    query = work_requests.insert().values(
        user_id=current_user["id"],
        is_premium=current_user["is_premium"],
        **request_data.dict()
    )
    last_record_id = await database.execute(query)
    return await database.fetch_one(work_requests.select().where(work_requests.c.id == last_record_id))

@api_router.get("/work_requests/by_city/{city_id}", response_model=List[WorkRequestOut])
async def get_work_requests_by_city(city_id: int, current_user: dict = Depends(get_current_user)):
    results = await database.fetch_all(work_requests.select().where(work_requests.c.city_id == city_id))
    
    response_data = []
    for r in results:
        request_dict = dict(r)
        if not current_user["is_premium"]:
            request_dict["phone_number"] = "Доступно премиум-исполнителям"
        response_data.append(request_dict)
    return response_data

@api_router.get("/work_requests/my", response_model=List[WorkRequestOut])
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] == "ЗАКАЗЧИК":
        query = work_requests.select().where(work_requests.c.user_id == current_user["id"])
    else: # ИСПОЛНИТЕЛЬ
        query = work_requests.select().where(work_requests.c.executor_id == current_user["id"])
    return await database.fetch_all(query)

# --- Offers System ---

@api_router.post("/work_requests/{request_id}/offer", status_code=status.HTTP_201_CREATED)
async def make_offer_for_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только ИСПОЛНИТЕЛЬ может предлагать услуги.")

    async with database.transaction():
        request_item = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
        if not request_item:
            raise HTTPException(status_code=404, detail="Заявка не найдена.")
        if request_item["is_taken"]:
            raise HTTPException(status_code=400, detail="Эта заявка уже принята.")

        if await database.fetch_one(work_request_offers.select().where(
            (work_request_offers.c.request_id == request_id) & 
            (work_request_offers.c.performer_id == current_user["id"])
        )):
            raise HTTPException(status_code=409, detail="Вы уже откликнулись на эту заявку.")

        await database.execute(work_request_offers.insert().values(request_id=request_id, performer_id=current_user["id"]))
    return {"message": "Вы успешно откликнулись на заявку."}

@api_router.get("/work_requests/{request_id}/offers", response_model=List[OfferOut])
async def get_offers_for_work_request(request_id: int, current_user: dict = Depends(get_current_user)):
    request_item = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not request_item or request_item["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Доступ запрещен.")

    query = select([work_request_offers, users]).where(
        work_request_offers.c.request_id == request_id
    ).select_from(work_request_offers.join(users, work_request_offers.c.performer_id == users.c.id))
    
    offers_data = await database.fetch_all(query)
    
    return [
        {
            "id": offer["id"], "request_id": offer["request_id"], "performer_id": offer["performer_id"],
            "timestamp": offer["timestamp"], "status": offer["status"],
            "performer": {**offer}
        } for offer in offers_data
    ]

@api_router.post("/work_requests/offers/{offer_id}/accept", status_code=status.HTTP_200_OK)
async def accept_offer(offer_id: int, current_user: dict = Depends(get_current_user)):
    async with database.transaction():
        offer = await database.fetch_one(work_request_offers.select().where(work_request_offers.c.id == offer_id))
        if not offer:
            raise HTTPException(status_code=404, detail="Предложение не найдено.")

        request_item = await database.fetch_one(work_requests.select().where(work_requests.c.id == offer["request_id"]))
        if not request_item or request_item["user_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Доступ запрещен.")
        if request_item["is_taken"]:
            raise HTTPException(status_code=400, detail="Исполнитель уже выбран.")

        await database.execute(work_requests.update().where(work_requests.c.id == offer["request_id"]).values(
            is_taken=True, executor_id=offer["performer_id"]
        ))
        await database.execute(work_request_offers.update().where(work_request_offers.c.id == offer_id).values(status="accepted"))
        await database.execute(work_request_offers.update().where(
            (work_request_offers.c.request_id == offer["request_id"]) & (work_request_offers.c.id != offer_id)
        ).values(status="rejected"))
    
    return {"message": "Исполнитель успешно выбран!"}

# --- Chat ---

# ИСПРАВЛЕНО: Этот эндпоинт теперь ЕДИНСТВЕННЫЙ и корректно работает
@api_router.websocket("/ws/chat/{request_id}/{opponent_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    request_id: int, 
    opponent_id: int,
    token: str = Query(...)
):
    try:
        user = await get_current_user(token)
        user_id = user["id"]
        username = user["email"].split("@")[0]
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    await manager.connect(websocket, request_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            
            query = chat_messages.insert().values(
                request_id=request_id,
                sender_id=user_id,
                recipient_id=opponent_id,
                message=data,
                timestamp=datetime.utcnow()
            )
            await database.execute(query)
            
            message_payload = json.dumps({
                "sender_id": user_id,
                "sender_name": username,
                "message": data,
                "time": datetime.utcnow().strftime("%H:%M")
            })
            await manager.broadcast(request_id, message_payload)

    except WebSocketDisconnect:
        manager.disconnect(websocket, request_id)
    except Exception:
        manager.disconnect(websocket, request_id)

@api_router.get("/work_requests/{request_id}/chat/{participant_id}", response_model=List[ChatMessageOut])
async def get_chat_messages_history(request_id: int, participant_id: int, current_user: dict = Depends(get_current_user)):
    # Здесь можно добавить логику проверки, имеет ли 'current_user' доступ к этому чату
    # (например, является ли он заказчиком или исполнителем по этой заявке)
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
        "user1_id": current_user['id'],
        "user2_id": participant_id
    })
    return messages

# ИСПРАВЛЕНО: Оптимизированный запрос для списка чатов
@api_router.get("/chats/my_active_chats", response_model=List[ChatSummary])
async def get_my_active_chats(current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    
    # Оптимизированный SQL-запрос для получения всех данных за один раз
    query = """
    WITH user_chats AS (
        -- Находим всех уникальных собеседников пользователя
        SELECT request_id, recipient_id as opponent_id FROM chat_messages WHERE sender_id = :user_id
        UNION
        SELECT request_id, sender_id as opponent_id FROM chat_messages WHERE recipient_id = :user_id
    ),
    latest_messages AS (
        -- Находим последнее сообщение в каждом диалоге с помощью оконной функции
        SELECT
            id,
            request_id,
            CASE
                WHEN sender_id = :user_id THEN recipient_id
                ELSE sender_id
            END as opponent_id,
            message,
            ROW_NUMBER() OVER(PARTITION BY request_id, 
                CASE 
                    WHEN sender_id = :user_id AND recipient_id != :user_id THEN recipient_id
                    WHEN sender_id != :user_id AND recipient_id = :user_id THEN sender_id
                END ORDER BY timestamp DESC) as rn
        FROM chat_messages
        WHERE sender_id = :user_id OR recipient_id = :user_id
    )
    SELECT DISTINCT
        uc.request_id,
        uc.opponent_id,
        u.email as opponent_name,
        lm.message as last_message
    FROM user_chats uc
    JOIN users u ON uc.opponent_id = u.id
    LEFT JOIN latest_messages lm ON uc.request_id = lm.request_id AND uc.opponent_id = lm.opponent_id AND lm.rn = 1
    WHERE uc.opponent_id != :user_id;
    """
    
    results = await database.fetch_all(query, values={"user_id": user_id})
    
    return [
        ChatSummary(
            request_id=row["request_id"],
            opponent_id=row["opponent_id"],
            opponent_name=row["opponent_name"].split("@")[0],
            last_message=row["last_message"] or "Начать диалог"
        ) for row in results
    ]

# --- Other Endpoints ---
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
async def get_machinery_requests_by_city(city_id: int):
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
async def get_tool_requests_by_city(city_id: int):
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
async def get_material_ads_by_city(city_id: int):
    query = material_ads.select().where(material_ads.c.city_id == city_id)
    return await database.fetch_all(query)

@api_router.get("/material_ads/my", response_model=List[MaterialAdOut])
async def get_my_material_ads(current_user: dict = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.user_id == current_user["id"])
    return await database.fetch_all(query)
    
# Include router and static files
app.include_router(api_router)

# Serve static files (index.html)
static_path = Path(__file__).parent
if (static_path / "index.html").exists():
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

    @app.get("/{full_path:path}")
    async def read_index(request: Request, full_path: str):
        return FileResponse(static_path / "index.html")