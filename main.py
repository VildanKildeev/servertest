import json
import uvicorn
import databases
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

app = FastAPI(title="СМЗ.РФ API")

api_router = APIRouter(prefix="/api")

# ИСПРАВЛЕНИЕ: Добавляем api_router в основное приложение
app.include_router(api_router)

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

class UserCreate(BaseModel):
    username: str
    password: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class UserInDB(UserCreate):
    id: int

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None

class WorkRequestCreate(BaseModel):
    work_type: str
    needs_visit: bool
    address: Optional[str] = None
    description: str
    city_id: int

class WorkRequestInDB(WorkRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    
class MachineryRequestCreate(BaseModel):
    machinery_type: str
    address: str
    is_min_order: bool
    is_preorder: bool
    preorder_date: Optional[datetime] = None
    description: Optional[str] = None
    city_id: int

class MachineryRequestInDB(MachineryRequestCreate):
    id: int
    user_id: int
    created_at: datetime

class ToolRequestCreate(BaseModel):
    tools: List[str]
    start_date: str
    end_date: str
    needs_delivery: bool
    delivery_address: Optional[str] = None
    description: Optional[str] = None
    city_id: int

class ToolRequestInDB(ToolRequestCreate):
    id: int
    user_id: int
    created_at: datetime

class MaterialAdCreate(BaseModel):
    material_type: str
    description: str
    price: float
    city_id: int

class MaterialAdInDB(MaterialAdCreate):
    id: int
    user_id: int
    created_at: datetime

# OAuth2PasswordBearer
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Здесь должна быть логика декодирования JWT и проверки пользователя
    # Поскольку у нас нет реального JWT, будем делать простую проверку
    user = await database.fetch_one(users.select().where(users.c.username == token))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

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
    return {"access_token": user.username, "token_type": "bearer"} # Используем username как простой токен

@api_router.post("/users/", response_model=UserInDB)
async def create_user(user: UserCreate):
    if await database.fetch_one(users.select().where(users.c.username == user.username)):
        raise HTTPException(status_code=400, detail="Username already registered")
    query = users.insert().values(
        username=user.username,
        password_hash=get_password_hash(user.password),
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization
    )
    last_record_id = await database.execute(query)
    return {**user.model_dump(), "id": last_record_id}

@api_router.get("/users/me", response_model=UserInDB)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    return current_user

@api_router.put("/users/update-specialization")
async def update_user_specialization(specialization_data: dict, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type not in ["ИСПОЛНИТЕЛЬ", "ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ"]:
        raise HTTPException(status_code=403, detail="Only executors or machinery owners can have a specialization")
    query = users.update().where(users.c.id == current_user.id).values(specialization=specialization_data.get("specialization"))
    await database.execute(query)
    return {"message": "Specialization updated successfully"}

@api_router.get("/users/my-requests", response_model=List[dict])
async def get_my_requests(current_user: UserInDB = Depends(get_current_user)):
    work_query = work_requests.select().where(work_requests.c.user_id == current_user.id)
    machinery_query = machinery_requests.select().where(machinery_requests.c.user_id == current_user.id)
    tool_query = tool_requests.select().where(tool_requests.c.user_id == current_user.id)
    material_query = material_ads.select().where(material_ads.c.user_id == current_user.id)

    work_reqs = await database.fetch_all(work_query)
    machinery_reqs = await database.fetch_all(machinery_query)
    tool_reqs = await database.fetch_all(tool_query)
    material_ads = await database.fetch_all(material_query)
    
    all_requests = []
    for req in work_reqs:
        all_requests.append({**req, "request_type": "work"})
    for req in machinery_reqs:
        all_requests.append({**req, "request_type": "machinery"})
    for req in tool_reqs:
        all_requests.append({**req, "request_type": "tool"})
    for req in material_ads:
        all_requests.append({**req, "request_type": "material_ad"})
        
    return all_requests

@api_router.post("/work-requests", response_model=WorkRequestInDB)
async def create_work_request(work_request: WorkRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = work_requests.insert().values(
        work_type=work_request.work_type,
        needs_visit=work_request.needs_visit,
        address=work_request.address,
        description=work_request.description,
        city_id=work_request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return {**work_request.model_dump(), "id": last_record_id, "user_id": current_user.id, "created_at": datetime.now()}

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def read_work_requests(city_id: Optional[int] = None):
    query = work_requests.select()
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return requests

@api_router.post("/work-requests/{request_id}/take")
async def take_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    # Логика для того, чтобы "взять" заявку
    # В реальном приложении здесь будет проверка, что пользователь имеет право взять заявку,
    # что она еще не взята и т.д.
    # Простая реализация:
    return {"message": f"Request {request_id} taken by user {current_user.id}"}

@api_router.post("/machinery-requests", response_model=MachineryRequestInDB)
async def create_machinery_request(machinery_request: MachineryRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = machinery_requests.insert().values(
        machinery_type=machinery_request.machinery_type,
        address=machinery_request.address,
        is_min_order=machinery_request.is_min_order,
        is_preorder=machinery_request.is_preorder,
        preorder_date=machinery_request.preorder_date,
        description=machinery_request.description,
        city_id=machinery_request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return {**machinery_request.model_dump(), "id": last_record_id, "user_id": current_user.id, "created_at": datetime.now()}

@api_router.post("/tool-requests", response_model=ToolRequestInDB)
async def create_tool_request(tool_request: ToolRequestCreate, current_user: UserInDB = Depends(get_current_user)):
    query = tool_requests.insert().values(
        tools=json.dumps(tool_request.tools),
        start_date=tool_request.start_date,
        end_date=tool_request.end_date,
        needs_delivery=tool_request.needs_delivery,
        delivery_address=tool_request.delivery_address,
        description=tool_request.description,
        city_id=tool_request.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return {**tool_request.model_dump(), "id": last_record_id, "user_id": current_user.id, "created_at": datetime.now()}

@api_router.post("/material-ads", response_model=MaterialAdInDB)
async def create_material_ad(ad: MaterialAdCreate, current_user: UserInDB = Depends(get_current_user)):
    query = material_ads.insert().values(
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        city_id=ad.city_id,
        user_id=current_user.id
    )
    last_record_id = await database.execute(query)
    return {**ad.model_dump(), "id": last_record_id, "user_id": current_user.id, "created_at": datetime.now()}

@api_router.get("/material-ads", response_model=List[MaterialAdInDB])
async def read_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id is not None:
        query = query.where(material_ads.c.city_id == city_id)
    ads = await database.fetch_all(query)
    return ads

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
        "Перфоратор", "Шуруповерт", "Болгарка", "Сварочный аппарат", "Отбойный молоток", "Генератор", "Компрессор", "Бетономешалка"
    ]
    return tools_list

app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)