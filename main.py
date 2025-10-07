import json
import uvicorn
import databases
import asyncpg
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import exc, select
from sqlalchemy import select, or_, and_ 

# --- Database setup ---
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, database, work_request_offers, cities

import os
from dotenv import load_dotenv
load_dotenv()

# Настройки для токенов
SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")

app = FastAPI(title="СМЗ.РФ - Backend", description="API для поиска работы и размещения объявлений")
api_router = APIRouter(prefix="/api")

# CORS middleware
origins = ["*"] # В продакшене заменить на конкретные домены
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Schemas (УБРАН is_premium) ---

class UserIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone_number: Optional[str] = None
    user_role: str = "worker"
    specialization: Optional[str] = None
    city_id: Optional[int] = None

class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    phone_number: Optional[str] = None
    user_role: str
    rating: float
    review_count: int
    specialization: Optional[str] = None
    city_id: Optional[int] = None

class WorkRequestIn(BaseModel):
    title: str
    description: str
    specialization: str
    budget: Optional[float] = None
    contact_info: str
    city_id: int

class WorkRequestOut(BaseModel):
    id: int
    customer_id: int
    title: str
    description: str
    specialization: str
    budget: Optional[float] = None
    contact_info: str # Всегда виден, так как убран Premium
    city_id: int
    status: str
    created_at: datetime
    is_rated: bool # Добавлено

class WorkRequestOfferIn(BaseModel):
    offer_price: Optional[float] = None
    comment: Optional[str] = None

class WorkRequestOfferOut(BaseModel):
    id: int
    request_id: int
    worker_id: int
    offer_price: Optional[float] = None
    comment: Optional[str] = None
    status: str
    created_at: datetime
    
class RatingIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    
class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    rental_start_date: Optional[date] = None
    rental_end_date: Optional[date] = None
    has_delivery: bool = False
    delivery_address: Optional[str] = None
    
class MachineryRequestOut(MachineryRequestIn):
    id: int
    user_id: int
    created_at: datetime

class ToolRequestIn(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    tool_count: int = 1
    rental_start_date: Optional[date] = None
    rental_end_date: Optional[date] = None
    has_delivery: bool = False
    delivery_address: Optional[str] = None

class ToolRequestOut(ToolRequestIn):
    id: int
    user_id: int
    created_at: datetime
    
class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

class MaterialAdOut(MaterialAdIn):
    id: int
    user_id: int
    created_at: datetime

# --- Security and Auth ---

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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

async def get_user_from_token(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    query = users.select().where(users.c.id == user_id)
    user_data = await database.fetch_one(query)
    
    if user_data is None:
        raise credentials_exception
    
    # УБРАНО: is_premium
    return {
        "id": user_data["id"],
        "email": user_data["email"],
        "full_name": user_data["full_name"],
        "user_role": user_data["user_role"],
        "phone_number": user_data["phone_number"],
        "city_id": user_data["city_id"],
    }

async def get_current_user(current_user: dict = Depends(get_user_from_token)):
    return current_user

# --- Authentication Routes ---

@api_router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(user: UserIn):
    try:
        hashed_password = get_password_hash(user.password)
        query = users.insert().values(
            email=user.email,
            hashed_password=hashed_password,
            full_name=user.full_name,
            phone_number=user.phone_number,
            user_role=user.user_role,
            specialization=user.specialization,
            city_id=user.city_id,
        )
        last_record_id = await database.execute(query)
        # Получаем созданного пользователя
        created_user = await database.fetch_one(users.select().where(users.c.id == last_record_id))
        return created_user
    except exc.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже существует.",
        )

@api_router.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    query = users.select().where(users.c.email == form_data.username)
    user = await database.fetch_one(query)
    
    if not user or not pwd_context.verify(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"user_id": user["id"], "sub": user["email"]},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "user_role": user["user_role"]}

@api_router.get("/users/me", response_model=UserOut)
async def read_users_me(current_user: dict = Depends(get_current_user)):
    query = users.select().where(users.c.id == current_user["id"])
    return await database.fetch_one(query)
    
@api_router.put("/users/me", response_model=UserOut)
async def update_users_me(update_data: Dict, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    data_to_update = {k: v for k, v in update_data.items() if k not in ["id", "email", "rating", "review_count"]}
    if "password" in data_to_update:
        data_to_update["hashed_password"] = get_password_hash(data_to_update.pop("password"))

    query = users.update().where(users.c.id == user_id).values(**data_to_update)
    await database.execute(query)
    
    return await database.fetch_one(users.select().where(users.c.id == user_id))

# --- Dictionary Routes ---
@api_router.get("/cities")
async def get_cities():
    query = cities.select()
    return await database.fetch_all(query)

@api_router.get("/specializations")
async def get_specializations():
    return [
        {"name": "Сантехник"},
        {"name": "Электрик"},
        {"name": "Плотник"},
        {"name": "Мастер по плитке"},
        {"name": "Сварщик"},
        {"name": "Кровельщик"},
    ]

# --- Work Requests Routes ---

@api_router.post("/work_requests", response_model=WorkRequestOut, status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestIn, current_user: dict = Depends(get_current_user)):
    query = work_requests.insert().values(
        customer_id=current_user["id"],
        title=request.title,
        description=request.description,
        specialization=request.specialization,
        budget=request.budget,
        contact_info=request.contact_info,
        city_id=request.city_id,
        status="open",
        # is_rated по умолчанию False
    )
    last_record_id = await database.execute(query)
    created_request_query = work_requests.select().where(work_requests.c.id == last_record_id)
    return await database.fetch_one(created_request_query)

@api_router.get("/work_requests/by_city/{city_id}", response_model=List[WorkRequestOut])
async def get_work_requests_by_city(city_id: int):
    # Фильтр по статусу "open"
    query = work_requests.select().where(
        and_(work_requests.c.city_id == city_id, work_requests.c.status == "open")
    ).order_by(work_requests.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.get("/work_requests/my", response_model=List[WorkRequestOut])
async def get_my_work_requests(current_user: dict = Depends(get_current_user)):
    query = work_requests.select().where(work_requests.c.customer_id == current_user["id"]).order_by(work_requests.c.created_at.desc())
    return await database.fetch_all(query)
    
# --- Rating Route (С ИСПРАВЛЕНИЕМ) ---
@api_router.post("/work_requests/{request_id}/rate", status_code=status.HTTP_204_NO_CONTENT)
async def rate_executor(request_id: int, rating_in: RatingIn, current_user: dict = Depends(get_current_user)):
    
    # 1. Проверка существования заявки и прав
    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request_data = await database.fetch_one(request_query)
    
    if not request_data:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    if request_data["customer_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Вы не являетесь заказчиком этой заявки и не можете ее оценить.")
        
    # 2. ПРОВЕРКА: Заявка уже оценена?
    if request_data["is_rated"]:
        raise HTTPException(status_code=400, detail="Эта заявка уже была оценена.")
        
    # 3. Находим принятого исполнителя
    accepted_offer_query = work_request_offers.select().where(
        and_(
            work_request_offers.c.request_id == request_id,
            work_request_offers.c.status == "accepted"
        )
    )
    accepted_offer = await database.fetch_one(accepted_offer_query)
    
    if not accepted_offer:
        raise HTTPException(status_code=400, detail="У этой заявки нет принятого исполнителя для оценки.")
        
    worker_id = accepted_offer["worker_id"]
    
    # 4. Обновляем рейтинг исполнителя
    worker_data = await database.fetch_one(users.select().where(users.c.id == worker_id))
    
    new_review_count = worker_data["review_count"] + 1
    current_total_rating = worker_data["rating"] * worker_data["review_count"]
    new_total_rating = current_total_rating + rating_in.rating
    new_average_rating = new_total_rating / new_review_count

    update_worker_query = users.update().where(users.c.id == worker_id).values(
        rating=new_average_rating,
        review_count=new_review_count
    )
    await database.execute(update_worker_query)
    
    # 5. Устанавливаем флаг is_rated = True для заявки
    update_request_query = work_requests.update().where(work_requests.c.id == request_id).values(is_rated=True)
    await database.execute(update_request_query)
    
    return

# --- Machinery Requests Routes ---

@api_router.post("/machinery_requests", response_model=MachineryRequestOut, status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestIn, current_user: dict = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        user_id=current_user["id"], **request.dict()
    )
    last_record_id = await database.execute(query)
    created_request_query = machinery_requests.select().where(machinery_requests.c.id == last_record_id)
    return await database.fetch_one(created_request_query)

@api_router.get("/machinery_requests/by_city/{city_id}", response_model=List[MachineryRequestOut])
async def get_machinery_requests_by_city(city_id: int):
    query = machinery_requests.select().where(machinery_requests.c.city_id == city_id).order_by(machinery_requests.c.created_at.desc())
    return await database.fetch_all(query)

# --- Tool Requests Routes ---

@api_router.post("/tool_requests", response_model=ToolRequestOut, status_code=status.HTTP_201_CREATED)
async def create_tool_request(request: ToolRequestIn, current_user: dict = Depends(get_current_user)):
    query = tool_requests.insert().values(
        user_id=current_user["id"], **request.dict()
    )
    last_record_id = await database.execute(query)
    created_request_query = tool_requests.select().where(tool_requests.c.id == last_record_id)
    return await database.fetch_one(created_request_query)

@api_router.get("/tool_requests/by_city/{city_id}", response_model=List[ToolRequestOut])
async def get_tool_requests_by_city(city_id: int):
    query = tool_requests.select().where(tool_requests.c.city_id == city_id).order_by(tool_requests.c.created_at.desc())
    return await database.fetch_all(query)

# --- Material Ads Routes ---

@api_router.post("/material_ads", response_model=MaterialAdOut, status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad: MaterialAdIn, current_user: dict = Depends(get_current_user)):
    query = material_ads.insert().values(
        user_id=current_user["id"], **ad.dict()
    )
    last_record_id = await database.execute(query)
    created_ad_query = material_ads.select().where(material_ads.c.id == last_record_id)
    return await database.fetch_one(created_ad_query)

@api_router.get("/material_ads/by_city/{city_id}", response_model=List[MaterialAdOut])
async def get_material_ads_by_city(city_id: int):
    query = material_ads.select().where(material_ads.c.city_id == city_id).order_by(material_ads.c.created_at.desc())
    return await database.fetch_all(query)

@api_router.get("/material_ads/my", response_model=List[MaterialAdOut])
async def get_my_material_ads(current_user: dict = Depends(get_current_user)):
    query = material_ads.select().where(material_ads.c.user_id == current_user["id"]).order_by(material_ads.c.created_at.desc())
    return await database.fetch_all(query)

# --- Static Files Mounting ---

app.include_router(api_router)

# Обслуживание статических файлов
# app.mount("/static", StaticFiles(directory="static"), name="static")

# Обслуживание index.html
@app.get("/", include_in_schema=False)
async def serve_app():
    return FileResponse('index.html')

# --- Lifespan Events ---
@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

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