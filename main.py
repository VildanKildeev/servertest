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
    metadata.create_all(engine)
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

class UserInDB(BaseModel):
    id: int
    username: str
    password_hash: str
    user_name: str
    user_type: str
    city_id: Optional[int]
    specialization: Optional[str]

class User(BaseModel):
    username: str
    user_name: str
    user_type: str
    city_id: Optional[int]
    specialization: Optional[str]

class UserData(BaseModel):
    username: str
    password: str
    user_name: str
    user_type: str
    city_id: Optional[int]
    specialization: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

class WorkRequestIn(BaseModel):
    title: str
    description: str
    contact_info: str
    budget: Optional[float] = None
    city_id: int
    specialization: str
    user_id: Optional[int] = None
    executor_id: Optional[int] = None

class WorkRequestInDB(WorkRequestIn):
    id: int
    user_id: int
    created_at: datetime
    
class MachineryRequestIn(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    hourly_rate: Optional[float] = None
    contact_info: str
    city_id: int
    user_id: Optional[int] = None

class MachineryRequestInDB(MachineryRequestIn):
    id: int
    user_id: int
    created_at: datetime

class ToolRequestIn(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: Optional[float] = None
    contact_info: str
    city_id: int
    user_id: Optional[int] = None

class ToolRequestInDB(ToolRequestIn):
    id: int
    user_id: int
    created_at: datetime
    
class MaterialAdIn(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: Optional[float] = None
    contact_info: str
    city_id: int
    user_id: Optional[int] = None
    
class MaterialAdInDB(MaterialAdIn):
    id: int
    user_id: int
    created_at: datetime

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

async def get_current_active_user(current_user: UserInDB = Depends(get_current_user)):
    return current_user

@api_router.post("/register", response_model=UserInDB)
async def register_user(user_data: UserData):
    query = users.select().where(users.c.username == user_data.username)
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Пользователь с таким именем уже существует"
        )
    hashed_password = get_password_hash(user_data.password)
    query = users.insert().values(
        username=user_data.username,
        password_hash=hashed_password,
        user_name=user_data.user_name,
        user_type=user_data.user_type,
        city_id=user_data.city_id,
        specialization=user_data.specialization
    )
    user_id = await database.execute(query)
    return {**user_data.dict(), "id": user_id, "password_hash": hashed_password}

@api_router.post("/login", response_model=Token)
async def login_for_access_token(user_data: UserData):
    query = users.select().where(users.c.username == user_data.username)
    user = await database.fetch_one(query)
    if not user or not verify_password(user_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неправильное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
    
@api_router.get("/me", response_model=UserInDB)
async def read_current_user(current_user: UserInDB = Depends(get_current_active_user)):
    return current_user

@api_router.post("/change-password")
async def change_password(
    password_change: PasswordChange,
    current_user: UserInDB = Depends(get_current_active_user)
):
    if not verify_password(password_change.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный старый пароль")
    
    new_hashed_password = get_password_hash(password_change.new_password)
    query = users.update().where(users.c.id == current_user.id).values(password_hash=new_hashed_password)
    await database.execute(query)
    
    return {"message": "Пароль успешно изменен"}

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(
    request_data: WorkRequestIn,
    current_user: UserInDB = Depends(get_current_active_user)
):
    if current_user.user_type not in ["ЗАКАЗЧИК", "ИСПОЛНИТЕЛЬ"]:
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ может создавать заявки на работы")
        
    query = work_requests.insert().values(
        title=request_data.title,
        description=request_data.description,
        contact_info=request_data.contact_info,
        budget=request_data.budget,
        city_id=request_data.city_id,
        specialization=request_data.specialization,
        user_id=current_user.id
    )
    request_id = await database.execute(query)
    
    request_in_db = {
        **request_data.dict(),
        "id": request_id,
        "user_id": current_user.id,
        "created_at": datetime.now()
    }
    return WorkRequestInDB(**request_in_db)

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def get_work_requests(
    city_id: Optional[int] = None,
    specialization: Optional[str] = None,
):
    query = work_requests.select()
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    if specialization is not None:
        query = query.where(work_requests.c.specialization == specialization)

    requests = await database.fetch_all(query)
    return [WorkRequestInDB(**req._mapping) for req in requests]

@api_router.post("/work-requests/{request_id}/take")
async def take_work_request(
    request_id: int,
    current_user: UserInDB = Depends(get_current_active_user)
):
    if current_user.user_type not in ["ИСПОЛНИТЕЛЬ"]:
        raise HTTPException(status_code=403, detail="Только ИСПОЛНИТЕЛЬ может принимать заявки на работы")
    
    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)
    
    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    
    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    # Обновляем заявку, присваивая исполнителя
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    return WorkRequestInDB(**request._mapping)

@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(
    request_data: MachineryRequestIn,
    current_user: UserInDB = Depends(get_current_active_user)
):
    if current_user.user_type not in ["ЗАКАЗЧИК", "ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ"]:
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК или ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ может создавать заявки на спецтехнику")
    
    query = machinery_requests.insert().values(
        machinery_type=request_data.machinery_type,
        description=request_data.description,
        hourly_rate=request_data.hourly_rate,
        contact_info=request_data.contact_info,
        city_id=request_data.city_id,
        user_id=current_user.id
    )
    request_id = await database.execute(query)
    
    request_in_db = {
        **request_data.dict(),
        "id": request_id,
        "user_id": current_user.id,
        "created_at": datetime.now()
    }
    return MachineryRequestInDB(**request_in_db)

@api_router.get("/machinery-requests", response_model=List[MachineryRequestInDB])
async def get_machinery_requests(
    city_id: Optional[int] = None,
    machinery_type: Optional[str] = None,
):
    query = machinery_requests.select()
    if city_id is not None:
        query = query.where(machinery_requests.c.city_id == city_id)
    if machinery_type is not None:
        query = query.where(machinery_requests.c.machinery_type == machinery_type)
        
    requests = await database.fetch_all(query)
    return [MachineryRequestInDB(**req._mapping) for req in requests]
    
@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(
    request_data: ToolRequestIn,
    current_user: UserInDB = Depends(get_current_active_user)
):
    if current_user.user_type not in ["ЗАКАЗЧИК"]:
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК может создавать заявки на инструменты")
    
    query = tool_requests.insert().values(
        tool_name=request_data.tool_name,
        description=request_data.description,
        rental_price=request_data.rental_price,
        contact_info=request_data.contact_info,
        city_id=request_data.city_id,
        user_id=current_user.id
    )
    request_id = await database.execute(query)
    
    request_in_db = {
        **request_data.dict(),
        "id": request_id,
        "user_id": current_user.id,
        "created_at": datetime.now()
    }
    return ToolRequestInDB(**request_in_db)

@api_router.get("/tool-requests", response_model=List[ToolRequestInDB])
async def get_tool_requests(
    city_id: Optional[int] = None,
    tool_name: Optional[str] = None,
):
    query = tool_requests.select()
    if city_id is not None:
        query = query.where(tool_requests.c.city_id == city_id)
    if tool_name is not None:
        query = query.where(tool_requests.c.tool_name == tool_name)
    
    requests = await database.fetch_all(query)
    return [ToolRequestInDB(**req._mapping) for req in requests]
    
@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(
    ad_data: MaterialAdIn,
    current_user: UserInDB = Depends(get_current_active_user)
):
    if current_user.user_type not in ["ЗАКАЗЧИК", "ИСПОЛНИТЕЛЬ"]:
        raise HTTPException(status_code=403, detail="Только ЗАКАЗЧИК или ИСПОЛНИТЕЛЬ может создавать объявления о материалах")
    
    query = material_ads.insert().values(
        material_type=ad_data.material_type,
        description=ad_data.description,
        price=ad_data.price,
        contact_info=ad_data.contact_info,
        city_id=ad_data.city_id,
        user_id=current_user.id
    )
    ad_id = await database.execute(query)
    
    ad_in_db = {
        **ad_data.dict(),
        "id": ad_id,
        "user_id": current_user.id,
        "created_at": datetime.now()
    }
    return MaterialAdInDB(**ad_in_db)
    
@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def get_material_ads(
    city_id: Optional[int] = None,
    material_type: Optional[str] = None,
):
    query = material_ads.select()
    if city_id is not None:
        query = query.where(material_ads.c.city_id == city_id)
    if material_type is not None:
        query = query.where(material_ads.c.material_type == material_type)
    
    ads = await database.fetch_all(query)
    # ✅ ИСПРАВЛЕНИЕ: Преобразуем данные в Pydantic-модели
    return [MaterialAdInDB(**ad._mapping) for ad in ads]

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

@api_router.get("/tool-types")
async def get_tool_types():
    tool_types = [
        "Отбойный молоток", "Вибратор для бетона", "Компрессор", "Сварочный аппарат", "Генератор", "Бетономешалка"
    ]
    return tool_types

@api_router.get("/material-types")
async def get_material_types():
    material_types = [
        "Бетон", "Кирпич", "Металлопрокат", "Лес", "Песок", "Щебень", "Цемент"
    ]
    return material_types


app.include_router(api_router)

# Mount the static directory
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)