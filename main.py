import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

import uvicorn
from fastapi import (
    FastAPI, HTTPException, status, Depends, APIRouter, Request, BackgroundTasks,
    WebSocket, WebSocketDisconnect, Query
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from sqlalchemy import select, and_, desc, func

from database import (
    database, metadata, engine,
    users, cities, subscriptions,
    work_requests, work_request_offers,
    machinery_requests, tool_requests, material_ads,
    chat_messages, machinery_types, tools_list, material_types
)

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")

app = FastAPI(title="Construction Hub API", version="1.0.0")
api_router = APIRouter(prefix="/api", tags=["api"])

# Allow all origins by default (tune for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static index if ./static exists
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", include_in_schema=False)
async def root_index():
    # Serve /static/index.html if available
    index_path = os.path.join("static", "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"ok": True, "message": "API root. Place your frontend in ./static/index.html"}

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    query = select(users).where(users.c.email == email.lower().strip())
    return await database.fetch_one(query)

async def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    query = select(users).where(users.c.id == user_id)
    return await database.fetch_one(query)

async def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    user = await get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user

async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[int] = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = await get_user_by_id(int(user_id))
    if user is None:
        raise credentials_exception
    return dict(user)

# ----------------------------------------------------------------------------
# Models (Pydantic)
# ----------------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserRegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    role: Optional[str] = Field(default="customer", description="customer|performer|owner")

class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: Optional[str] = None
    full_name: Optional[str] = None
    city_id: Optional[int] = None
    created_at: datetime

class City(BaseModel):
    id: int
    name: str

class SubscribeIn(BaseModel):
    city_id: int

class WorkRequestIn(BaseModel):
    title: str
    description: str
    city_id: int
    budget: Optional[float] = None

class WorkRequestOut(BaseModel):
    id: int
    user_id: int
    city_id: int
    title: str
    description: str
    budget: Optional[float] = None
    status: str
    created_at: datetime

class OfferIn(BaseModel):
    price: Optional[float] = None
    comment: Optional[str] = None

class OfferOut(BaseModel):
    id: int
    request_id: int
    performer_id: int
    status: str
    timestamp: datetime
    price: Optional[float] = None
    comment: Optional[str] = None

class MachineryRequestIn(BaseModel):
    city_id: int
    type: str
    title: str
    description: str

class ToolRequestIn(BaseModel):
    city_id: int
    tool: str
    title: str
    description: str

class MaterialAdIn(BaseModel):
    city_id: int
    material_type: str
    title: str
    description: str
    price: Optional[float] = None

class ChatMessageOut(BaseModel):
    id: int
    request_id: int
    sender_id: int
    receiver_id: int
    message: str
    timestamp: datetime

# ----------------------------------------------------------------------------
# Auth endpoints
# ----------------------------------------------------------------------------
@api_router.post("/register", response_model=UserOut)
async def register_user(payload: UserRegisterIn):
    existing = await get_user_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    values = {
        "email": payload.email.lower().strip(),
        "hashed_password": get_password_hash(payload.password),
        "role": payload.role,
        "created_at": datetime.utcnow()
    }
    user_id = await database.execute(users.insert().values(**values))
    user = await get_user_by_id(user_id)
    return user

@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token(data={"sub": str(user["id"]), "email": user["email"]})
    return {"access_token": token, "token_type": "bearer"}

@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    return current_user

# ----------------------------------------------------------------------------
# Cities & reference endpoints
# ----------------------------------------------------------------------------
@api_router.get("/cities", response_model=List[City])
async def get_cities():
    rows = await database.fetch_all(select(cities).order_by(cities.c.name))
    return rows

@api_router.get("/machinery_types", response_model=List[str])
async def get_machinery_types():
    rows = await database.fetch_all(select(machinery_types.c.name).order_by(machinery_types.c.name))
    return [r[0] for r in rows]

@api_router.get("/tools_list", response_model=List[str])
async def get_tools_list():
    rows = await database.fetch_all(select(tools_list.c.name).order_by(tools_list.c.name))
    return [r[0] for r in rows]

@api_router.get("/material_types", response_model=List[str])
async def get_material_types():
    rows = await database.fetch_all(select(material_types.c.name).order_by(material_types.c.name))
    return [r[0] for r in rows]

@api_router.post("/subscribe")
async def create_subscription(payload: SubscribeIn, current_user: Dict[str, Any] = Depends(get_current_user)):
    # prevent duplicates
    exists = await database.fetch_one(
        select(subscriptions.c.id).where(
            and_(subscriptions.c.user_id == current_user["id"], subscriptions.c.city_id == payload.city_id)
        )
    )
    if not exists:
        await database.execute(
            subscriptions.insert().values(user_id=current_user["id"], city_id=payload.city_id, created_at=datetime.utcnow())
        )
    return {"ok": True}

# ----------------------------------------------------------------------------
# Work requests & offers
# ----------------------------------------------------------------------------
@api_router.post("/work_requests", response_model=WorkRequestOut)
async def create_work_request(payload: WorkRequestIn, current_user: Dict[str, Any] = Depends(get_current_user)):
    values = {
        "user_id": current_user["id"],
        "city_id": payload.city_id,
        "title": payload.title,
        "description": payload.description,
        "budget": payload.budget,
        "status": "open",
        "created_at": datetime.utcnow()
    }
    new_id = await database.execute(work_requests.insert().values(**values))
    row = await database.fetch_one(select(work_requests).where(work_requests.c.id == new_id))
    return row

@api_router.get("/work_requests", response_model=List[WorkRequestOut])
async def list_work_requests(city_id: Optional[int] = None, limit: int = 50, offset: int = 0):
    q = select(work_requests).order_by(desc(work_requests.c.created_at)).limit(limit).offset(offset)
    if city_id:
        q = select(work_requests).where(work_requests.c.city_id == city_id).order_by(desc(work_requests.c.created_at)).limit(limit).offset(offset)
    rows = await database.fetch_all(q)
    return rows

@api_router.post("/work_requests/{request_id}/offers", response_model=OfferOut)
async def create_offer(request_id: int, payload: OfferIn, current_user: Dict[str, Any] = Depends(get_current_user)):
    # Ensure request exists
    wr = await database.fetch_one(select(work_requests.c.id).where(work_requests.c.id == request_id))
    if not wr:
        raise HTTPException(status_code=404, detail="Work request not found")
    values = {
        "request_id": request_id,
        "performer_id": current_user["id"],
        "price": payload.price,
        "comment": payload.comment,
        "status": "pending",
        "timestamp": datetime.utcnow()
    }
    new_id = await database.execute(work_request_offers.insert().values(**values))
    row = await database.fetch_one(select(work_request_offers).where(work_request_offers.c.id == new_id))
    return row

@api_router.get("/work_requests/{request_id}/offers", response_model=List[OfferOut])
async def list_offers(request_id: int):
    rows = await database.fetch_all(
        select(work_request_offers).where(work_request_offers.c.request_id == request_id).order_by(desc(work_request_offers.c.timestamp))
    )
    return rows

# ----------------------------------------------------------------------------
# Machinery / Tools / Materials
# ----------------------------------------------------------------------------
@api_router.post("/machinery_requests")
async def create_machinery_request(payload: MachineryRequestIn, current_user: Dict[str, Any] = Depends(get_current_user)):
    values = {
        "user_id": current_user["id"],
        "city_id": payload.city_id,
        "type": payload.type,
        "title": payload.title,
        "description": payload.description,
        "created_at": datetime.utcnow()
    }
    new_id = await database.execute(machinery_requests.insert().values(**values))
    row = await database.fetch_one(select(machinery_requests).where(machinery_requests.c.id == new_id))
    return row

@api_router.get("/machinery_requests")
async def list_machinery_requests(city_id: Optional[int] = None, limit: int = 50, offset: int = 0):
    q = select(machinery_requests).order_by(desc(machinery_requests.c.created_at)).limit(limit).offset(offset)
    if city_id:
        q = select(machinery_requests).where(machinery_requests.c.city_id == city_id).order_by(desc(machinery_requests.c.created_at)).limit(limit).offset(offset)
    return await database.fetch_all(q)

@api_router.post("/tool_requests")
async def create_tool_request(payload: ToolRequestIn, current_user: Dict[str, Any] = Depends(get_current_user)):
    values = {
        "user_id": current_user["id"],
        "city_id": payload.city_id,
        "tool": payload.tool,
        "title": payload.title,
        "description": payload.description,
        "created_at": datetime.utcnow()
    }
    new_id = await database.execute(tool_requests.insert().values(**values))
    row = await database.fetch_one(select(tool_requests).where(tool_requests.c.id == new_id))
    return row

@api_router.get("/tool_requests")
async def list_tool_requests(city_id: Optional[int] = None, limit: int = 50, offset: int = 0):
    q = select(tool_requests).order_by(desc(tool_requests.c.created_at)).limit(limit).offset(offset)
    if city_id:
        q = select(tool_requests).where(tool_requests.c.city_id == city_id).order_by(desc(tool_requests.c.created_at)).limit(limit).offset(offset)
    return await database.fetch_all(q)

@api_router.post("/material_ads")
async def create_material_ad(payload: MaterialAdIn, current_user: Dict[str, Any] = Depends(get_current_user)):
    values = {
        "user_id": current_user["id"],
        "city_id": payload.city_id,
        "material_type": payload.material_type,
        "title": payload.title,
        "description": payload.description,
        "price": payload.price,
        "created_at": datetime.utcnow()
    }
    new_id = await database.execute(material_ads.insert().values(**values))
    row = await database.fetch_one(select(material_ads).where(material_ads.c.id == new_id))
    return row

@api_router.get("/material_ads")
async def list_material_ads(city_id: Optional[int] = None, limit: int = 50, offset: int = 0):
    q = select(material_ads).order_by(desc(material_ads.c.created_at)).limit(limit).offset(offset)
    if city_id:
        q = select(material_ads).where(material_ads.c.city_id == city_id).order_by(desc(material_ads.c.created_at)).limit(limit).offset(offset)
    return await database.fetch_all(q)

# ----------------------------------------------------------------------------
# Chats
# ----------------------------------------------------------------------------
@api_router.get("/chats/my_active_chats")
async def my_active_chats(current_user: Dict[str, Any] = Depends(get_current_user)):
    # return distinct pairs by request_id & opponent_id for the current user
    # opponent is either sender or receiver other than current user
    rows = await database.fetch_all(
        select(
            chat_messages.c.request_id,
            func.min(chat_messages.c.timestamp).label("first_message_at"),
            func.max(chat_messages.c.timestamp).label("last_message_at")
        ).where(
            (chat_messages.c.sender_id == current_user["id"]) | (chat_messages.c.receiver_id == current_user["id"])
        ).group_by(chat_messages.c.request_id).order_by(desc("last_message_at"))
    )
    return [dict(r) for r in rows]

# ----------------------------------------------------------------------------
# WebSocket chat
# ----------------------------------------------------------------------------
class ConnectionManager:
    """Manage active WS connections per request_id."""
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, request_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(request_id, []).append(websocket)

    def disconnect(self, request_id: int, websocket: WebSocket):
        conns = self.active_connections.get(request_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns and request_id in self.active_connections:
            self.active_connections.pop(request_id, None)

    async def broadcast(self, request_id: int, message: str):
        for ws in list(self.active_connections.get(request_id, [])):
            try:
                await ws.send_text(message)
            except Exception:
                # drop dead sockets
                self.disconnect(request_id, ws)

manager = ConnectionManager()

@api_router.websocket("/ws/chat/{request_id}/{opponent_id}")
async def websocket_endpoint(websocket: WebSocket, request_id: int, opponent_id: int, token: str = Query(...)):
    # authenticate
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[int] = int(payload.get("sub"))
        if user_id is None:
            await websocket.close(code=4401)
            return
    except JWTError:
        await websocket.close(code=4401)
        return

    await manager.connect(request_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            # Save message
            msg_id = await database.execute(chat_messages.insert().values(
                request_id=request_id,
                sender_id=user_id,
                receiver_id=opponent_id,
                message=data,
                timestamp=datetime.utcnow()
            ))
            # enrich payload
            sender = await get_user_by_id(user_id)
            payload = {
                "id": msg_id,
                "request_id": request_id,
                "sender_id": user_id,
                "sender_email": sender["email"] if sender else None,
                "receiver_id": opponent_id,
                "message": data,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            await manager.broadcast(request_id, json.dumps(payload))
    except WebSocketDisconnect:
        manager.disconnect(request_id, websocket)
    except Exception:
        manager.disconnect(request_id, websocket)
        await websocket.close()

# ----------------------------------------------------------------------------
# Lifespan
# ----------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    # Ensure tables exist
    metadata.create_all(engine)
    await database.connect()
    # Seed reference data if empty
    if await database.fetch_val(select(func.count()).select_from(cities)) == 0:
        await database.execute_many(cities.insert(), [
            {"name": n} for n in ["Москва", "Санкт-Петербург", "Казань", "Нижний Новгород", "Новосибирск"]
        ])
    if await database.fetch_val(select(func.count()).select_from(machinery_types)) == 0:
        await database.execute_many(machinery_types.insert(), [
            {"name": n} for n in ["Экскаватор", "Бульдозер", "Кран", "Каток"]
        ])
    if await database.fetch_val(select(func.count()).select_from(tools_list)) == 0:
        await database.execute_many(tools_list.insert(), [
            {"name": n} for n in ["Перфоратор", "Болгарка", "Отбойный молоток"]
        ])
    if await database.fetch_val(select(func.count()).select_from(material_types)) == 0:
        await database.execute_many(material_types.insert(), [
            {"name": n} for n in ["Песок", "Щебень", "Цемент", "Кирпич"]
        ])

@app.on_event("shutdown")
async def on_shutdown():
    await database.disconnect()

app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))