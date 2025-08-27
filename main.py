import json
import uvicorn
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, status, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from passlib.context import CryptContext

import databases
import sqlalchemy  # <-- This line was missing
from sqlalchemy.schema import MetaData
from sqlalchemy.engine import create_engine
import os
from dotenv import load_dotenv

load_dotenv()

# === DATABASE SETUP ===
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("Переменная окружения DATABASE_URL не установлена.")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
metadata = MetaData()

database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# === Таблицы (должны совпадать с index.html и API) ===
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("username", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("password_hash", sqlalchemy.String),
    sqlalchemy.Column("user_name", sqlalchemy.String),
    sqlalchemy.Column("user_type", sqlalchemy.String),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("specialization", sqlalchemy.String, nullable=True),
)

work_requests = sqlalchemy.Table(
    "work_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("work_type", sqlalchemy.String),
    sqlalchemy.Column("needs_visit", sqlalchemy.Boolean),
    sqlalchemy.Column("address", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("description", sqlalchemy.String),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

machinery_requests = sqlalchemy.Table(
    "machinery_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("machinery_type", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("address", sqlalchemy.String),
    sqlalchemy.Column("is_min_order", sqlalchemy.Boolean),
    sqlalchemy.Column("is_preorder", sqlalchemy.Boolean),
    sqlalchemy.Column("preorder_date", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

tool_requests = sqlalchemy.Table(
    "tool_requests",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("tools", sqlalchemy.String), # JSON-строка
    sqlalchemy.Column("description", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("needs_delivery", sqlalchemy.Boolean),
    sqlalchemy.Column("delivery_address", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("start_date", sqlalchemy.String),
    sqlalchemy.Column("end_date", sqlalchemy.String),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

material_ads = sqlalchemy.Table(
    "material_ads",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("city_id", sqlalchemy.Integer),
    sqlalchemy.Column("material_type", sqlalchemy.String),
    sqlalchemy.Column("description", sqlalchemy.String),
    sqlalchemy.Column("price", sqlalchemy.Float),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
)

# === Subscriptions ===
subscriptions = sqlalchemy.Table(
    "subscriptions",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("user_id", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id")),
    sqlalchemy.Column("active", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("expiry", sqlalchemy.DateTime, nullable=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=sqlalchemy.func.now()),
    sqlalchemy.UniqueConstraint("user_id", name="uq_user_subscription"),
)

metadata.create_all(engine)

# === Pydantic Models ===
class UserBase(BaseModel):
    username: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    id: int

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class WorkRequestBase(BaseModel):
    city_id: int
    work_type: str
    needs_visit: bool
    address: Optional[str] = None
    description: Optional[str] = None

class WorkRequestInDB(WorkRequestBase):
    id: int
    user_id: int
    created_at: datetime

class MachineryRequestBase(BaseModel):
    city_id: int
    machinery_type: str
    address: str
    description: Optional[str] = None
    is_min_order: bool = False
    is_preorder: bool = False
    preorder_date: Optional[datetime] = None

class MachineryRequestInDB(MachineryRequestBase):
    id: int
    user_id: int
    created_at: datetime

class ToolRequestBase(BaseModel):
    city_id: int
    tools: List[str]
    description: Optional[str] = None
    needs_delivery: bool = False
    delivery_address: Optional[str] = None
    start_date: str
    end_date: str

class ToolRequestInDB(ToolRequestBase):
    id: int
    user_id: int
    created_at: datetime

class MaterialAdBase(BaseModel):
    city_id: int
    material_type: str
    description: str
    price: float

class MaterialAdInDB(MaterialAdBase):
    id: int
    user_id: int
    created_at: datetime

class SubscriptionBase(BaseModel):
    active: bool
    expiry: Optional[datetime] = None

class SubscriptionInDB(SubscriptionBase):
    id: int
    user_id: int
    created_at: datetime

# === API APP SETUP ===
app = FastAPI(title="СМЗ.РФ API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# === Dependencies ===
def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token_data = TokenData(username=username)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await get_user(token_data.username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

async def get_user(username: str):
    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    if user:
        return dict(user)
    return None

# === API ENDPOINTS ===
@api_router.post("/users/", response_model=UserInDB, status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate):
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization
    )
    last_record_id = await database.execute(query)
    return {**user.dict(), "id": last_record_id}

# Other endpoints...

@api_router.post("/work-requests", response_model=WorkRequestInDB, status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestBase, current_user: dict = Depends(get_current_user)):
    query = work_requests.insert().values(
        user_id=current_user["id"],
        city_id=request.city_id,
        work_type=request.work_type,
        needs_visit=request.needs_visit,
        address=request.address,
        description=request.description
    )
    last_record_id = await database.execute(query)
    return {**request.dict(), "id": last_record_id, "user_id": current_user["id"], "created_at": datetime.now()}

# other endpoints...

# === HTML/Static Files ===
app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)