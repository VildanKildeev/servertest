import json
import uvicorn
import databases
from jose import jwt, JWTError
from datetime import timedelta
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

import os
from dotenv import load_dotenv
load_dotenv()

from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL

database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

app = FastAPI(title="СМЗ.РФ API")

api_router = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    # Создаем таблицы, используя синхронный движок
    from sqlalchemy.schema import MetaData
    from sqlalchemy.engine import create_engine
    import os
    
    DATABASE_URL = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://", 1)
    engine = create_engine(DATABASE_URL)
    metadata = MetaData()
    metadata.reflect(bind=engine) # Отражаем текущее состояние БД
    
    # Создаем все таблицы, которые еще не существуют
    metadata.create_all(bind=engine, checkfirst=True)
    
    # Теперь подключаемся к базе данных
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# =======================================================
#               МОДЕЛИ Pydantic
# =======================================================

class UserBase(BaseModel):
    username: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserPublic(UserBase):
    id: int

class UserInDB(UserBase):
    id: int
    password_hash: str
    created_at: Optional[datetime] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class WorkRequestCreate(BaseModel):
    description: str
    budget: float
    contact_info: str
    city_id: int
    specialization: Optional[str] = None

class WorkRequestInDB(WorkRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    executor_id: Optional[int] = None

class MachineryRequestCreate(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class MachineryRequestInDB(MachineryRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    
class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class ToolRequestInDB(ToolRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    
class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: Optional[str] = None
    city_id: int

class MaterialAdInDB(MaterialAdCreate):
    id: int
    user_id: int
    created_at: datetime

# Теперь, когда все зависимые модели определены, можно определить MyRequestsResponse
class MyRequestsResponse(BaseModel):
    work_requests: List[WorkRequestInDB]
    machinery_requests: List[MachineryRequestInDB]
    tool_requests: List[ToolRequestInDB]
    material_ads: List[MaterialAdInDB]

# =======================================================
#               ФУНКЦИИ АУТЕНТИФИКАЦИИ
# =======================================================

from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

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
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    if user is None:
        raise credentials_exception
    return UserInDB(**user._mapping)

# =======================================================
#               ОБЩИЕ ФУНКЦИИ
# =======================================================

async def create_record_and_return(table, data_to_insert, response_model, current_user=None):
    """
    Общая функция для создания записи в базе данных.
    
    Args:
        table: SQLAlchemy таблица.
        data_to_insert: Словарь с данными для вставки в БД.
        response_model: Pydantic-модель для ответа API.
        current_user: Текущий аутентифицированный пользователь.
    """
    if current_user:
        data_to_insert["user_id"] = current_user.id
    query = table.insert().values(**data_to_insert)
    last_record_id = await database.execute(query)
    new_record_data = {
        "id": last_record_id,
        "created_at": datetime.now(),
        **data_to_insert
    }
    return response_model(**new_record_data)

# =======================================================
#               МАРШРУТЫ API
# =======================================================

@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    query = users.select().where(users.c.username == form_data.username)
    user = await database.fetch_one(query)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.post("/users/", response_model=UserPublic)
async def create_user(user: UserCreate):
    if await database.fetch_one(users.select().where(users.c.username == user.username)):
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = get_password_hash(user.password)
    data_to_insert = {
        "username": user.username,
        "password_hash": hashed_password,
        "user_name": user.user_name,
        "user_type": user.user_type,
        "city_id": user.city_id,
        "specialization": user.specialization,
    }
    return await create_record_and_return(
        table=users,
        data_to_insert=data_to_insert,
        response_model=UserPublic
    )

@api_router.put("/users/update-specialization")
async def update_user_specialization(specialization: str, current_user: UserInDB = Depends(get_current_user)):
    # Проверяем, что пользователь имеет право обновлять специализацию
    if current_user.user_type not in ["ИСПОЛНИТЕЛЬ", "ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ"]:
        raise HTTPException(status_code=403, detail="Только Исполнители и Владельцы спецтехники могут обновлять специализацию.")

    query = users.update().where(users.c.id == current_user.id).values(specialization=specialization)
    await database.execute(query)
    return {"message": "Специализация успешно обновлена."}

@api_router.get("/users/me", response_model=UserPublic)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    return UserPublic(**current_user._mapping)

@api_router.get("/users/my-requests", response_model=MyRequestsResponse)
async def read_my_requests(current_user: UserInDB = Depends(get_current_user)):
    work_query = work_requests.select().where(work_requests.c.user_id == current_user.id)
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == current_user.id)
    tool_query = tool_requests.select().where(tool_requests.c.user_id == current_user.id)
    material_query = material_ads.select().where(material_ads.c.user_id == current_user.id)
    
    work_results = await database.fetch_all(work_query)
    machinery_results = await database.fetch_all(machinery_query)
    tool_results = await database.fetch_all(tool_query)
    material_results = await database.fetch_all(material_query)
    
    return {
        "work_requests": [WorkRequestInDB(**r._mapping) for r in work_results],
        "machinery_requests": [MachineryRequestInDB(**r._mapping) for r in machinery_results],
        "tool_requests": [ToolRequestInDB(**r._mapping) for r in tool_results],
        "material_ads": [MaterialAdInDB(**r._mapping) for r in material_results],
    }

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(request: WorkRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    if not request.specialization:
        raise HTTPException(status_code=400, detail="Специализация не может быть пустой.")
    
    data_to_insert = request.model_dump()
    return await create_record_and_return(
        table=work_requests,
        data_to_insert=data_to_insert,
        response_model=WorkRequestInDB,
        current_user=current_user
    )

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def read_work_requests(city_id: Optional[int] = None):
    query = work_requests.select()
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
        
    requests = await database.fetch_all(query)
    # ✅ ИСПРАВЛЕНИЕ: Преобразуем данные в Pydantic-модели
    return [WorkRequestInDB(**r._mapping) for r in requests]

@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(request: MachineryRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    data_to_insert = request.model_dump()
    return await create_record_and_return(
        table=machinery_requests,
        data_to_insert=data_to_insert,
        response_model=MachineryRequestInDB,
        current_user=current_user
    )

@api_router.get("/machinery-requests", response_model=List[MachineryRequestInDB])
async def read_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select()
    if city_id is not None:
        query = query.where(machinery_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [MachineryRequestInDB(**r._mapping) for r in requests]

@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(request: ToolRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    data_to_insert = request.model_dump()
    return await create_record_and_return(
        table=tool_requests,
        data_to_insert=data_to_insert,
        response_model=ToolRequestInDB,
        current_user=current_user
    )

@api_router.get("/tool-requests", response_model=List[ToolRequestInDB])
async def read_tool_requests(city_id: Optional[int] = None):
    query = tool_requests.select()
    if city_id is not None:
        query = query.where(tool_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return [ToolRequestInDB(**r._mapping) for r in requests]

@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(ad: MaterialAdCreate, current_user: UserInDB = Depends(get_current_user)):
    data_to_insert = ad.model_dump()
    return await create_record_and_return(
        table=material_ads,
        data_to_insert=data_to_insert,
        response_model=MaterialAdInDB,
        current_user=current_user
    )

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def read_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id is not None:
        query = query.where(material_ads.c.city_id == city_id)
    
    ads = await database.fetch_all(query)
    return [MaterialAdInDB(**ad._mapping) for ad in ads]

@api_router.post("/work-requests/{request_id}/take", response_model=WorkRequestInDB)
async def take_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    # Проверяем, что пользователь является ИСПОЛНИТЕЛЕМ
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только Исполнитель может принять заявку на работу.")

    # Получаем заявку из базы данных
    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)

    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    # Если у заявки уже есть исполнитель, ее нельзя взять
    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    # Обновляем заявку, присваивая исполнителя
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    return WorkRequestInDB(**request._mapping)

@api_router.get("/cities")
async def get_cities():
    cities = [
        {"id": 1, "name": "Москва"},
        {"id": 2, "name": "Санкт-Петербург"},
        {"id": 3, "name": "Казань"},
        {"id": 4, "name": "Екатеринбург"},
        {"id": 5, "name": "Новосибирск"},
    ]
    return cities

@api_router.get("/specializations")
async def get_specializations():
    specializations = [
        "Отделочник", "Сантехник", "Электрик", "Мастер по мебели", "Мастер на час", "Уборка", "Проектирование"
    ]
    return specializations

@api_router.get("/machinery-types")
async def get_machinery_types():
    machinery_types = [
        "Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Ямобур", "Манипулятор", "Погрузчик", "Эвакуатор"
    ]
    return machinery_types

@api_router.get("/tools-list")
async def get_tools_list():
    tools_list = [
        "Бетономешалка", "Отбойный молоток", "Перфоратор", "Лазерный уровень", "Строительный пылесос"
    ]
    return tools_list

app.include_router(api_router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")