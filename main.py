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
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

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
    metadata.create_all(engine)
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# Models
class User(BaseModel):
    username: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None
    is_premium: Optional[bool] = False

class UserInDB(User):
    id: int
    password_hash: str
    is_premium: bool

class UserUpdateSpecialization(BaseModel):
    specialization: str

class UserProfile(BaseModel):
    user_name: str
    username: str
    user_type: str
    city_id: int
    specialization: Optional[str]
    is_premium: bool

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class WorkRequest(BaseModel):
    description: str
    budget: float
    contact_info: str
    specialization: str

class WorkRequestInDB(WorkRequest):
    id: int
    user_id: int
    city_id: int
    is_premium: bool
    executor_id: Optional[int]
    created_at: datetime

class MachineryRequest(BaseModel):
    machinery_type: str
    description: str
    rental_price: float
    contact_info: str

class MachineryRequestInDB(MachineryRequest):
    id: int
    user_id: int
    city_id: int
    created_at: datetime

class ToolRequest(BaseModel):
    tool_name: str
    description: str
    rental_price: float
    contact_info: str

class ToolRequestInDB(ToolRequest):
    id: int
    user_id: int
    city_id: int
    created_at: datetime

class MaterialAd(BaseModel):
    material_type: str
    description: str
    price: float
    contact_info: str

class MaterialAdInDB(MaterialAd):
    id: int
    user_id: int
    city_id: int
    created_at: datetime
    
class MyRequests(BaseModel):
    work_requests: List[WorkRequestInDB]
    machinery_requests: List[MachineryRequestInDB]
    tool_requests: List[ToolRequestInDB]
    material_ads: List[MaterialAdInDB]

# Security functions
def get_password_hash(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str):
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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Недействительные учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    query = users.select().where(users.c.username == token_data.username)
    user = await database.fetch_one(query)
    if user is None:
        raise credentials_exception
    return user

# API Endpoints
@api_router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    query = users.select().where(users.c.username == form_data.username)
    user = await database.fetch_one(query)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неправильный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@api_router.post("/users/", response_model=User)
async def create_user(user: User):
    query = users.select().where(users.c.username == user.username)
    if await database.fetch_one(query):
        raise HTTPException(status_code=400, detail="Это имя пользователя уже занято.")
    
    hashed_password = get_password_hash(user.password)
    query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization,
        is_premium=user.is_premium
    )
    last_record_id = await database.execute(query)
    return {**user.dict(), "id": last_record_id}

@api_router.get("/users/me", response_model=UserProfile)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    return UserProfile(**current_user._mapping)

@api_router.put("/users/update-specialization", response_model=UserProfile)
async def update_user_specialization(
    specialization_data: UserUpdateSpecialization,
    current_user: UserInDB = Depends(get_current_user)
):
    query = users.update().where(users.c.id == current_user.id).values(specialization=specialization_data.specialization)
    await database.execute(query)
    updated_user_query = users.select().where(users.c.id == current_user.id)
    updated_user = await database.fetch_one(updated_user_query)
    return UserProfile(**updated_user._mapping)

@api_router.post("/subscribe")
async def subscribe_user(current_user: UserInDB = Depends(get_current_user)):
    if current_user.is_premium:
        raise HTTPException(status_code=400, detail="У вас уже есть премиум-подписка.")
    
    update_query = users.update().where(users.c.id == current_user.id).values(is_premium=True)
    await database.execute(update_query)
    
    return {"message": "Премиум-подписка успешно активирована!"}

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(request: WorkRequest, current_user: UserInDB = Depends(get_current_user)):
    query = work_requests.insert().values(
        description=request.description,
        budget=request.budget,
        contact_info=request.contact_info,
        city_id=current_user.city_id,
        user_id=current_user.id,
        specialization=request.specialization,
        is_premium=current_user.is_premium
    )
    last_record_id = await database.execute(query)
    
    created_request_query = work_requests.select().where(work_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    
    return WorkRequestInDB(**created_request._mapping)

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def get_work_requests():
    query = work_requests.select().where(work_requests.c.executor_id == None).order_by(work_requests.c.is_premium.desc(), work_requests.c.created_at.desc())
    requests = await database.fetch_all(query)
    return [WorkRequestInDB(**req._mapping) for req in requests]

@api_router.post("/work-requests/{request_id}/take", response_model=WorkRequestInDB)
async def take_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только пользователи типа 'ИСПОЛНИТЕЛЬ' могут принимать заявки.")

    request_query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(request_query)
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")
    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    return WorkRequestInDB(**request._mapping)

@api_router.get("/users/my-requests", response_model=MyRequests)
async def get_my_requests(current_user: UserInDB = Depends(get_current_user)):
    work_query = work_requests.select().where(work_requests.c.user_id == current_user.id)
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == current_user.id)
    tool_query = tool_requests.select().where(tool_requests.c.user_id == current_user.id)
    material_query = material_ads.select().where(material_ads.c.user_id == current_user.id)
    
    work_list = await database.fetch_all(work_query)
    machinery_list = await database.fetch_all(machinery_query)
    tool_list = await database.fetch_all(tool_query)
    material_list = await database.fetch_all(material_query)
    
    return MyRequests(
        work_requests=[WorkRequestInDB(**req._mapping) for req in work_list],
        machinery_requests=[MachineryRequestInDB(**req._mapping) for req in machinery_list],
        tool_requests=[ToolRequestInDB(**req._mapping) for req in tool_list],
        material_ads=[MaterialAdInDB(**ad._mapping) for ad in material_list]
    )

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
        "Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Грейдер", "Погрузчик", "Бетономешалка"
    ]
    return machinery_types

@api_router.get("/tools-list")
async def get_tools_list():
    tools_list = [
        "Перфоратор", "Шуруповерт", "Болгарка", "Сварочный аппарат", "Лазерный уровень", "Строительный фен"
    ]
    return tools_list

@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(request: MachineryRequest, current_user: UserInDB = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        machinery_type=request.machinery_type,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=current_user.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    
    created_request_query = machinery_requests.select().where(machinery_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    
    return MachineryRequestInDB(**created_request._mapping)

@api_router.get("/machinery-requests", response_model=List[MachineryRequestInDB])
async def get_machinery_requests():
    query = machinery_requests.select().order_by(machinery_requests.c.created_at.desc())
    requests = await database.fetch_all(query)
    return [MachineryRequestInDB(**req._mapping) for req in requests]

@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(request: ToolRequest, current_user: UserInDB = Depends(get_current_user)):
    query = tool_requests.insert().values(
        tool_name=request.tool_name,
        description=request.description,
        rental_price=request.rental_price,
        contact_info=request.contact_info,
        city_id=current_user.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    
    created_request_query = tool_requests.select().where(tool_requests.c.id == last_record_id)
    created_request = await database.fetch_one(created_request_query)
    
    return ToolRequestInDB(**created_request._mapping)

@api_router.get("/tool-requests", response_model=List[ToolRequestInDB])
async def get_tool_requests():
    query = tool_requests.select().order_by(tool_requests.c.created_at.desc())
    requests = await database.fetch_all(query)
    return [ToolRequestInDB(**req._mapping) for req in requests]

@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(ad: MaterialAd, current_user: UserInDB = Depends(get_current_user)):
    query = material_ads.insert().values(
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        contact_info=ad.contact_info,
        city_id=current_user.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    
    created_ad_query = material_ads.select().where(material_ads.c.id == last_record_id)
    created_ad = await database.fetch_one(created_ad_query)
    
    return MaterialAdInDB(**created_ad._mapping)

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def get_material_ads():
    query = material_ads.select().order_by(material_ads.c.created_at.desc())
    ads = await database.fetch_all(query)
    return [MaterialAdInDB(**ad._mapping) for ad in ads]


app.include_router(api_router)

# Обслуживаем главную страницу index.html
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())