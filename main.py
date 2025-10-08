
import os
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, status, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, Field, EmailStr

from database import (
    database, create_all,
    users, cities, specializations, machinery_types, tool_types, material_types,
    work_requests, work_request_ratings, machinery_requests, tool_requests, material_ads,
    INITIAL_CITIES, INITIAL_SPECIALIZATIONS, INITIAL_MACHINERY_TYPES, INITIAL_TOOL_TYPES, INITIAL_MATERIAL_TYPES
)

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------

SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key-change-me"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = int(os.environ.get("ACCESS_TOKEN_EXPIRE_DAYS", "7"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")

app = FastAPI(title="SMZ API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")

# ----------------------------------------------------------------------------
# Pydantic models
# ----------------------------------------------------------------------------

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserIn(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    user_type: str  # 'ЗАКАЗЧИК'|'ИСПОЛНИТЕЛЬ'|'ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ'
    phone_number: Optional[str] = None
    city_id: Optional[int] = None
    specialization: Optional[str] = None

class UserOut(BaseModel):
    id: int
    email: EmailStr
    first_name: str
    user_type: str
    phone_number: Optional[str] = None
    city_id: Optional[int] = None
    specialization: Optional[str] = None
    rating: float = 0.0
    rating_count: int = 0

class WorkRequestIn(BaseModel):
    name: str
    specialization: str
    description: str
    budget: Optional[float] = None
    phone_number: str
    city_id: int
    address: Optional[str] = None
    visit_date: Optional[datetime] = None

class RatingIn(BaseModel):
    rating_value: int = Field(ge=1, le=5)

class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: Optional[float] = None
    contact_info: str
    city_id: int
    delivery_date: Optional[datetime] = None

class ToolRequestIn(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: Optional[float] = None
    contact_info: str
    city_id: int
    has_delivery: bool = False
    delivery_address: Optional[str] = None
    rental_start_date: Optional[datetime] = None
    rental_end_date: Optional[datetime] = None

class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int
    is_premium: bool = False

class RefOut(BaseModel):
    id: int
    name: str

# ----------------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_user_by_email(email: str):
    query = users.select().where(users.c.email == email)
    return await database.fetch_one(query)

async def get_user_by_id(user_id: int):
    query = users.select().where(users.c.id == user_id)
    return await database.fetch_one(query)

async def get_current_user(token: str = Depends(oauth2_scheme)):
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
    if not user:
        raise credentials_exception
    return dict(user)

def to_user_out(row) -> UserOut:
    d = dict(row)
    return UserOut(
        id=d["id"],
        email=d["email"],
        first_name=d["first_name"],
        user_type=d["user_type"],
        phone_number=d.get("phone_number"),
        city_id=d.get("city_id"),
        specialization=d.get("specialization"),
        rating=float(d.get("rating") or 0.0),
        rating_count=int(d.get("rating_count") or 0),
    )

def row_to_ref(row) -> RefOut:
    d = dict(row)
    return RefOut(id=d["id"], name=d["name"])

# ----------------------------------------------------------------------------
# Auth endpoints
# ----------------------------------------------------------------------------

@api_router.post("/register", response_model=UserOut)
async def register(user: UserIn):
    if user.user_type not in ("ЗАКАЗЧИК", "ИСПОЛНИТЕЛЬ", "ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ"):
        raise HTTPException(400, "Некорректный тип пользователя.")
    if await get_user_by_email(user.email):
        raise HTTPException(400, "Пользователь с таким email уже существует.")
    hashed = get_password_hash(user.password)
    query = users.insert().values(
        email=user.email,
        hashed_password=hashed,
        first_name=user.first_name,
        user_type=user.user_type,
        phone_number=user.phone_number,
        city_id=user.city_id,
        specialization=user.specialization if user.user_type == "ИСПОЛНИТЕЛЬ" else None,
        rating=0.0,
        rating_count=0,
        created_at=datetime.utcnow(),
    )
    user_id = await database.execute(query)
    row = await get_user_by_id(user_id)
    return to_user_out(row)

@api_router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await get_user_by_email(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Неверный email или пароль.")
    token = create_access_token({"sub": str(user["id"])})
    return Token(access_token=token)

@api_router.get("/users/me", response_model=UserOut)
async def read_me(current_user: dict = Depends(get_current_user)):
    return to_user_out(current_user)

@api_router.put("/users/me", response_model=UserOut)
async def update_me(payload: dict, current_user: dict = Depends(get_current_user)):
    upd = {}
    if "first_name" in payload:    upd["first_name"] = payload["first_name"]
    if "phone_number" in payload:  upd["phone_number"] = payload["phone_number"]
    if "specialization" in payload and current_user["user_type"] == "ИСПОЛНИТЕЛЬ":
        upd["specialization"] = payload["specialization"]
    if not upd:
        return to_user_out(current_user)
    await database.execute(users.update().where(users.c.id == current_user["id"]).values(**upd))
    row = await get_user_by_id(current_user["id"])
    return to_user_out(row)

# ----------------------------------------------------------------------------
# Reference endpoints (DB-backed only)
# ----------------------------------------------------------------------------

@api_router.get("/cities/", response_model=List[RefOut])
async def get_cities():
    rows = await database.fetch_all(cities.select().order_by(cities.c.name))
    return [row_to_ref(r) for r in rows]

@api_router.get("/specializations/", response_model=List[RefOut])
async def get_specializations():
    rows = await database.fetch_all(specializations.select().order_by(specializations.c.name))
    return [row_to_ref(r) for r in rows]

@api_router.get("/machinery_types/", response_model=List[RefOut])
async def get_machinery_types():
    rows = await database.fetch_all(machinery_types.select().order_by(machinery_types.c.name))
    return [row_to_ref(r) for r in rows]

@api_router.get("/tool_types/", response_model=List[RefOut])
async def get_tool_types():
    rows = await database.fetch_all(tool_types.select().order_by(tool_types.c.name))
    return [row_to_ref(r) for r in rows]

@api_router.get("/material_types/", response_model=List[RefOut])
async def get_material_types():
    rows = await database.fetch_all(material_types.select().order_by(material_types.c.name))
    return [row_to_ref(r) for r in rows]

# ----------------------------------------------------------------------------
# Work requests (jobs)
# ----------------------------------------------------------------------------

@api_router.post("/work_requests")
async def create_work_request(payload: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    if current_user["user_type"] != "ЗАКАЗЧИК":
        raise HTTPException(403, "Только ЗАКАЗЧИК может создавать заявки.")
    if current_user.get("phone_number") and payload.phone_number != current_user["phone_number"]:
        raise HTTPException(400, "Телефон в заявке должен совпадать с телефоном в профиле.")
    q = work_requests.insert().values(
        user_id=current_user["id"],
        city_id=payload.city_id,
        name=payload.name,
        specialization=payload.specialization,
        description=payload.description,
        budget=payload.budget,
        phone_number=payload.phone_number,
        address=payload.address,
        visit_date=payload.visit_date,
        status="open",
        created_at=datetime.utcnow(),
    )
    wr_id = await database.execute(q)
    return {"id": wr_id}

@api_router.get("/work_requests/by_city/{city_id}")
async def list_work_requests(city_id: int):
    q = work_requests.select().where(
        (work_requests.c.city_id == city_id) & (work_requests.c.status == "open")
    ).order_by(work_requests.c.created_at.desc())
    return [dict(r) for r in await database.fetch_all(q)]

@api_router.get("/work_requests/my")
async def my_work_requests(current_user: dict = Depends(get_current_user)):
    q = work_requests.select().where(work_requests.c.user_id == current_user["id"]).order_by(work_requests.c.created_at.desc())
    return [dict(r) for r in await database.fetch_all(q)]

@api_router.post("/work_requests/{request_id}/rate")
async def rate_executor(request_id: int, rating: RatingIn, current_user: dict = Depends(get_current_user)):
    req = await database.fetch_one(work_requests.select().where(work_requests.c.id == request_id))
    if not req:
        raise HTTPException(404, "Заявка не найдена.")
    if req["user_id"] != current_user["id"]:
        raise HTTPException(403, "Вы не являетесь автором заявки.")
    if not req["executor_id"]:
        raise HTTPException(400, "Заявка ещё не принята исполнителем.")

    already = await database.fetch_one(
        work_request_ratings.select().where(
            (work_request_ratings.c.work_request_id == request_id) &
            (work_request_ratings.c.rater_id == current_user["id"])
        )
    )
    if already:
        raise HTTPException(400, "Вы уже оценили эту заявку.")

    await database.execute(work_request_ratings.insert().values(
        work_request_id=request_id,
        rater_id=current_user["id"],
        executor_id=req["executor_id"],
        rating_value=rating.rating_value
    ))

    executor = await database.fetch_one(users.select().where(users.c.id == req["executor_id"]))
    if not executor:
        raise HTTPException(404, "Исполнитель не найден.")
    old_total = float(executor["rating"] or 0.0) * int(executor["rating_count"] or 0)
    new_count = int(executor["rating_count"] or 0) + 1
    new_avg = (old_total + rating.rating_value) / new_count
    await database.execute(users.update().where(users.c.id == executor["id"]).values(
        rating=new_avg, rating_count=new_count
    ))
    return {"ok": True}

# ----------------------------------------------------------------------------
# Ads: machinery, tools, materials
# ----------------------------------------------------------------------------

@api_router.post("/machinery_requests/")
async def create_machinery(payload: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    q = machinery_requests.insert().values(
        user_id=current_user["id"],
        city_id=payload.city_id,
        machinery_type=payload.machinery_type,
        description=payload.description,
        rental_price=payload.rental_price,
        contact_info=payload.contact_info,
        delivery_date=payload.delivery_date,
        created_at=datetime.utcnow(),
    )
    ad_id = await database.execute(q)
    return {"id": ad_id}

@api_router.get("/machinery_requests/by_city/{city_id}")
async def list_machinery(city_id: int):
    q = machinery_requests.select().where(machinery_requests.c.city_id == city_id).order_by(
        machinery_requests.c.created_at.desc()
    )
    return [dict(r) for r in await database.fetch_all(q)]

@api_router.post("/tool_requests/")
async def create_tool(payload: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    q = tool_requests.insert().values(
        user_id=current_user["id"],
        city_id=payload.city_id,
        tool_name=payload.tool_name,
        description=payload.description,
        rental_price=payload.rental_price,
        contact_info=payload.contact_info,
        has_delivery=payload.has_delivery,
        delivery_address=payload.delivery_address,
        rental_start_date=payload.rental_start_date,
        rental_end_date=payload.rental_end_date,
        created_at=datetime.utcnow(),
    )
    ad_id = await database.execute(q)
    return {"id": ad_id}

@api_router.get("/tool_requests/by_city/{city_id}")
async def list_tools(city_id: int):
    q = tool_requests.select().where(tool_requests.c.city_id == city_id).order_by(
        tool_requests.c.created_at.desc()
    )
    return [dict(r) for r in await database.fetch_all(q)]

@api_router.post("/material_ads")
async def create_material(payload: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    if current_user.get("phone_number") and payload.contact_info != current_user["phone_number"]:
        raise HTTPException(400, "Контакт в объявлении должен совпадать с телефоном в профиле.")
    q = material_ads.insert().values(
        user_id=current_user["id"],
        city_id=payload.city_id,
        material_type=payload.material_type,
        description=payload.description,
        price=payload.price,
        contact_info=payload.contact_info,
        is_premium=payload.is_premium,
        created_at=datetime.utcnow(),
    )
    ad_id = await database.execute(q)
    return {"id": ad_id}

@api_router.get("/material_ads/by_city/{city_id}")
async def list_materials(city_id: int):
    q = material_ads.select().where(material_ads.c.city_id == city_id).order_by(
        material_ads.c.is_premium.desc(), material_ads.c.created_at.desc()
    )
    return [dict(r) for r in await database.fetch_all(q)]

@api_router.get("/my_ads")
async def my_ads(current_user: dict = Depends(get_current_user)):
    res = []
    for row in await database.fetch_all(machinery_requests.select().where(machinery_requests.c.user_id == current_user["id"])):
        d = dict(row); d["type"] = "machinery"; res.append(d)
    for row in await database.fetch_all(tool_requests.select().where(tool_requests.c.user_id == current_user["id"])):
        d = dict(row); d["type"] = "tool"; res.append(d)
    for row in await database.fetch_all(material_ads.select().where(material_ads.c.user_id == current_user["id"])):
        d = dict(row); d["type"] = "material"; res.append(d)
    res.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)
    return res

# ----------------------------------------------------------------------------
# Startup / shutdown
# ----------------------------------------------------------------------------

async def populate_reference_table(table, names: List[str]):
    existing = {r["name"] for r in await database.fetch_all(table.select())}
    to_insert = [ {"name": n} for n in names if n not in existing ]
    if to_insert:
        await database.execute_many(table.insert(), to_insert)

@app.on_event("startup")
async def on_startup():
    create_all()
    await database.connect()
    await populate_reference_table(cities, INITIAL_CITIES)
    await populate_reference_table(specializations, INITIAL_SPECIALIZATIONS)
    await populate_reference_table(machinery_types, INITIAL_MACHINERY_TYPES)
    await populate_reference_table(tool_types, INITIAL_TOOL_TYPES)
    await populate_reference_table(material_types, INITIAL_MATERIAL_TYPES)

@app.on_event("shutdown")
async def on_shutdown():
    await database.disconnect()

# Подключаем API-роутер
app.include_router(api_router)

# Раздача статического фронта из папки "static" (рядом с main.py), если она есть
from pathlib import Path as _P
_static_dir = _P(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
