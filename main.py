import os
import json
from datetime import timedelta, datetime, date
from typing import Optional, List

import asyncpg
import databases
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text, and_, or_, func, select

from database import (
    metadata, engine, database,
    users, work_requests, machinery_requests, tool_requests, material_ads, cities, ratings
)

load_dotenv()

# ===== App & CORS =====
app = FastAPI(title="СМЗ.РФ API", redirect_slashes=True)

# Allow all origins by default; tighten in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Auth
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")

api = APIRouter(prefix="/api")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_user_from_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            return None
        row = await database.fetch_one(users.select().where(users.c.email == email))
        return dict(row) if row else None
    except JWTError:
        return None

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    user = await get_user_from_token(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user

async def get_optional_user(request: Request) -> Optional[dict]:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1]
        return await get_user_from_token(token)
    return None

# ===== Pydantic models =====
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    phone_number: Optional[str] = None
    user_type: Optional[str] = "ЗАКАЗЧИК"
    specialization: Optional[str] = None
    city_id: Optional[int] = None

class UserOut(BaseModel):
    id: int
    email: EmailStr
    phone_number: Optional[str] = None
    user_type: str
    specialization: Optional[str] = None
    is_premium: bool
    city_id: Optional[int] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class RatingIn(BaseModel):
    request_id: int = Field(..., description="ID заявки")
    request_type: str = Field(..., description="Тип заявки: 'WORK' или 'MACHINERY'")
    score: int = Field(..., ge=1, le=5, description="Оценка 1..5")
    comment: Optional[str] = Field(None, description="Комментарий")

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
    status: Optional[str] = None
    is_master_visit_required: Optional[bool] = None

class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_date: Optional[date] = None
    min_rental_hours: int = 4
    rental_price: Optional[float] = None
    contact_info: Optional[str] = None
    city_id: int
    is_premium: bool = False
    has_delivery: bool = False
    delivery_address: Optional[str] = None

class ToolRequestIn(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: Optional[float] = None
    contact_info: Optional[str] = None
    city_id: int
    count: int = 1
    rental_start_date: Optional[date] = None
    rental_end_date: Optional[date] = None
    has_delivery: bool = False
    delivery_address: Optional[str] = None

class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: Optional[float] = None
    contact_info: Optional[str] = None
    city_id: int
    is_premium: bool = False

# ===== Startup / Shutdown =====
@app.on_event("startup")
async def on_startup():
    await database.connect()
    metadata.create_all(engine)
    # idempotent DDL
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE material_ads ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE"))
    # seed cities if empty
    row = await database.fetch_one(select(func.count(cities.c.id)))
    if row and row[0] == 0:
        default_cities = [
            {"name": "Москва"}, {"name": "Санкт-Петербург"}, {"name": "Новосибирск"},
            {"name": "Екатеринбург"}, {"name": "Казань"}, {"name": "Нижний Новгород"},
            {"name": "Челябинск"}, {"name": "Самара"}, {"name": "Омск"}, {"name": "Ростов-на-Дону"}
        ]
        await database.execute_many(query=cities.insert(), values=default_cities)

@app.on_event("shutdown")
async def on_shutdown():
    await database.disconnect()

# ===== Auth =====
@api.post("/register", response_model=UserOut, status_code=201)
async def register(user: UserCreate):
    exists = await database.fetch_one(users.select().where(users.c.email == user.email))
    if exists:
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует.")
    hashed = get_password_hash(user.password)
    values = {
        "email": user.email,
        "hashed_password": hashed,
        "phone_number": user.phone_number,
        "user_type": user.user_type or "ЗАКАЗЧИК",
        "specialization": user.specialization,
        "city_id": user.city_id,
    }
    uid = await database.execute(users.insert().values(**values))
    row = await database.fetch_one(users.select().where(users.c.id == uid))
    return dict(row)

@api.post("/token", response_model=Token)
async def token(form: OAuth2PasswordRequestForm = Depends()):
    row = await database.fetch_one(users.select().where(users.c.email == form.username))
    if not row or not verify_password(form.password, row["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    access_token = create_access_token({"sub": row["email"]}, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer"}

@api.get("/users/me", response_model=UserOut)
async def me(current_user: dict = Depends(get_current_user)):
    return current_user

# ===== Requests CRUD (create + list) =====
@api.post("/work_requests/", status_code=201)
async def create_work(req: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    values = req.dict()
    values["user_id"] = current_user["id"]
    rid = await database.execute(work_requests.insert().values(**values))
    return {"id": rid, **req.dict()}

@api.get("/work_requests/")
async def list_work(city_id: Optional[int] = None, current_user: Optional[dict] = Depends(get_optional_user)):
    q = work_requests.select()
    filter_city = current_user.get("city_id") if current_user and current_user.get("city_id") is not None else city_id
    if filter_city is not None:
        q = q.where(work_requests.c.city_id == filter_city)
    return await database.fetch_all(q)

@api.post("/machinery_requests/", status_code=201)
async def create_machinery(req: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    values = req.dict()
    values["user_id"] = current_user["id"]
    rid = await database.execute(machinery_requests.insert().values(**values))
    return {"id": rid, **req.dict()}

@api.get("/machinery_requests/")
async def list_machinery(city_id: Optional[int] = None, current_user: Optional[dict] = Depends(get_optional_user)):
    q = machinery_requests.select()
    filter_city = current_user.get("city_id") if current_user and current_user.get("city_id") is not None else city_id
    if filter_city is not None:
        q = q.where(machinery_requests.c.city_id == filter_city)
    return await database.fetch_all(q)

@api.post("/tool_requests/", status_code=201)
async def create_tool(req: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    values = req.dict()
    values["user_id"] = current_user["id"]
    rid = await database.execute(tool_requests.insert().values(**values))
    return {"id": rid, **req.dict()}

@api.get("/tool_requests/")
async def list_tool(city_id: Optional[int] = None, current_user: Optional[dict] = Depends(get_optional_user)):
    q = tool_requests.select()
    filter_city = current_user.get("city_id") if current_user and current_user.get("city_id") is not None else city_id
    if filter_city is not None:
        q = q.where(tool_requests.c.city_id == filter_city)
    return await database.fetch_all(q)

# ===== Material ads =====
@api.post("/material_ads/", status_code=201)
async def create_material(ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    values = ad.dict()
    values["user_id"] = current_user["id"]
    rid = await database.execute(material_ads.insert().values(**values))
    return {"id": rid, **ad.dict()}

@api.get("/material_ads/")
async def list_material(city_id: Optional[int] = None, current_user: Optional[dict] = Depends(get_optional_user)):
    q = material_ads.select()
    filter_city = current_user.get("city_id") if current_user and current_user.get("city_id") is not None else city_id
    if filter_city is not None:
        q = q.where(material_ads.c.city_id == filter_city)
    return await database.fetch_all(q)

# ===== "Take" actions =====
@api.patch("/work_requests/{request_id}/take")
async def take_work(request_id: int, current_user: dict = Depends(get_current_user)):
    row = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not row:
        raise HTTPException(404, "Заявка не найдена.")
    if row["status"] != "active":
        raise HTTPException(400, "Эта заявка уже принята или закрыта.")
    await database.execute(
        work_requests.update().where(work_requests.c.id == request_id).values(status="В РАБОТЕ", executor_id=current_user["id"])
    )
    return {"message": "Заявка успешно принята.", "request_id": request_id}

@api.patch("/machinery_requests/{request_id}/take")
async def take_machinery(request_id: int, current_user: dict = Depends(get_current_user)):
    row = await database.fetch_one(machinery_requests.select().where(machinery_requests.c.id == request_id))
    if not row:
        raise HTTPException(404, "Заявка на технику не найдена.")
    if row["status"] != "active":
        raise HTTPException(400, "Эта заявка уже принята или закрыта.")
    await database.execute(
        machinery_requests.update().where(machinery_requests.c.id == request_id).values(status="В РАБОТЕ", executor_id=current_user["id"])
    )
    return {"message": "Заявка на технику успешно принята.", "request_id": request_id}

# ===== Ratings =====
@api.post("/ratings", status_code=201)
async def create_rating(rating: RatingIn, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ЗАКАЗЧИК":
        raise HTTPException(403, "Только Заказчик может оставлять рейтинг.")
    rtype = rating.request_type.upper()
    if rtype not in ("WORK", "MACHINERY"):
        raise HTTPException(400, "request_type должен быть 'WORK' или 'MACHINERY'")
    table = work_requests if rtype == "WORK" else machinery_requests
    row = await database.fetch_one(table.select().where(table.c.id == rating.request_id))
    if not row:
        raise HTTPException(404, "Заявка не найдена.")
    if row.get("executor_id") is None:
        raise HTTPException(400, "Исполнитель ещё не назначен для этой заявки.")
    # уникальность гарантирует БД, но проверим вручную для понятного ответа
    exist = await database.fetch_one(
        ratings.select().where(and_(ratings.c.request_id == rating.request_id, ratings.c.request_type == rtype))
    )
    if exist:
        raise HTTPException(409, "Рейтинг для этой заявки уже был выставлен.")
    await database.execute(
        ratings.insert().values(
            customer_id=current_user["id"],
            executor_id=row["executor_id"],
            request_id=rating.request_id,
            request_type=rtype,
            score=rating.score,
            comment=rating.comment,
        )
    )
    return {"message": f"Рейтинг {rating.score}/5 сохранён."}

@api.get("/executor_rating/{user_id}")
async def executor_rating(user_id: int):
    # ensure user exists and is Исполнитель
    u = await database.fetch_one(users.select().where(users.c.id == user_id))
    if not u:
        raise HTTPException(404, "Пользователь не найден.")
    if u["user_type"] != "ИСПОЛНИТЕЛЬ":
        return {"message": "Пользователь не является исполнителем. Рейтинг не применим."}
    row = await database.fetch_one(
        select(func.avg(ratings.c.score).label("average_rating"), func.count(ratings.c.id).label("total_ratings")).where(ratings.c.executor_id == user_id)
    )
    avg = float(row["average_rating"]) if row and row["average_rating"] is not None else 0.0
    total = int(row["total_ratings"]) if row else 0
    return {"executor_id": user_id, "average_rating": round(avg, 2), "total_ratings": total}

# ===== Offers (read-only mock with ratings enrichment) =====
@api.get("/requests/{request_type}/{request_id}/offers")
async def offers(request_type: str, request_id: int, current_user: dict = Depends(get_current_user)):
    rtype = request_type.upper()
    table = work_requests if rtype == "WORK" else machinery_requests
    req = await database.fetch_one(table.select().where(table.c.id == request_id))
    if not req or req["user_id"] != current_user["id"]:
        raise HTTPException(403, "Доступ запрещён или заявка не найдена.")
    # TODO: заменить на реальную таблицу/запрос предложений
    offers_data = [
        {"offer_id": 101, "executor_id": 2, "executor_username": "Иван-мастер", "offer_details": "Готов начать завтра."},
        {"offer_id": 102, "executor_id": 3, "executor_username": "ООО Спецтехника", "offer_details": "Цена включает доставку."}
    ]
    enriched = []
    for off in offers_data:
        row = await database.fetch_one(
            select(func.avg(ratings.c.score).label("avg"), func.count(ratings.c.id).label("cnt")).where(ratings.c.executor_id == off["executor_id"])
        )
        avg = float(row["avg"]) if row and row["avg"] is not None else 0.0
        cnt = int(row["cnt"]) if row else 0
        enriched.append({**off, "executor_rating_avg": round(avg, 2), "executor_rating_count": cnt})
    return enriched

# ===== Directories =====
SPECIALIZATIONS = [
    "Электрик","Сантехник","Сварщик","Плотник","Кровельщик","Маляр","Штукатур","Каменщик","Фасадчик",
    "Отделочник","Монтажник","Демонтажник","Разнорабочий","Мебельщик","Сборщик мебели","Ландшафтный дизайнер"
]

MACHINERY_TYPES = [
    "Экскаватор","Погрузчик","Манипулятор","Дорожный каток","Самосвал","Автокран","Автовышка"
]

TOOLS_LIST = [
    "Перфоратор","Лазерный нивелир","Бензопила","Сварочный аппарат","Шуруповерт",
    "Болгарка","Строительный пылесос","Тепловая пушка","Мотобур","Вибратор для бетона"
]

MATERIAL_TYPES = ["Цемент","Песок","Щебень","Кирпич","Бетон","Гипсокартон","Штукатурка","Шпаклевка","Краски","Клей","Грунтовка"]

@api.get("/specializations/")
def get_specializations():
    return SPECIALIZATIONS

@api.get("/machinery_types/")
def get_machinery_types():
    return MACHINERY_TYPES

@api.get("/tools_list/")
def get_tools_list():
    return TOOLS_LIST

@api.get("/material_types/")
def get_material_types():
    return MATERIAL_TYPES

@api.get("/cities/")
async def get_cities():
    return await database.fetch_all(cities.select().order_by(cities.c.name))

# ===== My requests (owner) with is_rated flag =====
async def _append_is_rated_flag(items, rtype: str, customer_id: int):
    result = []
    for it in items:
        rated = await database.fetch_one(
            ratings.select().where(and_(ratings.c.request_id == it["id"], ratings.c.request_type == rtype, ratings.c.customer_id == customer_id))
        )
        it = dict(it)
        it["is_rated"] = bool(rated)
        result.append(it)
    return result

@api.get("/my/work_requests")
async def my_work(current_user: dict = Depends(get_current_user)):
    items = await database.fetch_all(work_requests.select().where(work_requests.c.user_id == current_user["id"]).order_by(work_requests.c.created_at.desc()))
    return await _append_is_rated_flag(items, "WORK", current_user["id"])

@api.get("/my/machinery_requests")
async def my_machinery(current_user: dict = Depends(get_current_user)):
    items = await database.fetch_all(machinery_requests.select().where(machinery_requests.c.user_id == current_user["id"]).order_by(machinery_requests.c.created_at.desc()))
    return await _append_is_rated_flag(items, "MACHINERY", current_user["id"])

@api.get("/my/tool_requests")
async def my_tools(current_user: dict = Depends(get_current_user)):
    return await database.fetch_all(tool_requests.select().where(tool_requests.c.user_id == current_user["id"]).order_by(tool_requests.c.created_at.desc()))

# ===== Subscribe (accept both /subscribe and /subscribe/) =====
@api.post("/subscribe")
@api.post("/subscribe/")
async def subscribe(current_user: dict = Depends(get_current_user)):
    if current_user.get("is_premium"):
        return {"message": "Премиум уже активен."}
    await database.execute(users.update().where(users.c.id == current_user["id"]).values(is_premium=True))
    return {"message": "Премиум активирован."}

# ===== Update specialization =====
@api.post("/update_specialization/")
async def update_specialization(specialization: str, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(403, "Только ИСПОЛНИТЕЛЬ может менять специализацию.")
    await database.execute(users.update().where(users.c.id == current_user["id"]).values(specialization=specialization))
    return {"message": "Специализация обновлена."}

# Mount API router
app.include_router(api)

# Root -> serve SPA
@app.get("/")
def index():
    path = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(path)
