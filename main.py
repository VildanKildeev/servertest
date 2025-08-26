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
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer
import os
from dotenv import load_dotenv
load_dotenv()

from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL

database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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

# --- Новые зависимости для аутентификации ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

def get_database():
    return database

async def get_current_user(token: str = Depends(oauth2_scheme), database: databases.Database = Depends(get_database)):
    try:
        payload = jwt.decode(token, os.getenv("SECRET_KEY"), algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    
    query = users.select().where(users.c.username == username)
    user = await database.fetch_one(query)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
# --- Конец новых зависимостей ---

class UserCreate(BaseModel):
    username: str
    password: str
    user_name: str
    user_type: str
    city_id: int
    specialization: Optional[str] = None

class TokenData(BaseModel):
    username: Optional[str] = None

class LoginData(BaseModel):
    username: str
    password: str

class WorkRequestCreate(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int
    specialization: str

class MachineryRequestCreate(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int

@api_router.post("/register")
async def register(user: UserCreate):
    hashed_password = pwd_context.hash(user.password)
    query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        user_name=user.user_name,
        user_type=user.user_type,
        city_id=user.city_id,
        specialization=user.specialization
    )
    user_id = await database.execute(query)
    return {"id": user_id, "username": user.username}

@api_router.post("/token")
async def login_for_access_token(form_data: LoginData):
    query = users.select().where(users.c.username == form_data.username)
    user = await database.fetch_one(query)

    if not user or not pwd_context.verify(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = datetime.utcnow() + datetime.timedelta(minutes=30)
    access_token = jwt.encode({"sub": user["username"], "exp": access_token_expires}, os.getenv("SECRET_KEY"), algorithm="HS256")
    return {"access_token": access_token, "token_type": "bearer", "user_name": user["user_name"], "user_type": user["user_type"]}

@api_router.get("/users/me")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    return {"username": current_user["username"], "user_type": current_user["user_type"], "city_id": current_user["city_id"], "user_name": current_user["user_name"]}

@api_router.post("/work-requests")
async def create_work_request(request: WorkRequestCreate, current_user: dict = Depends(get_current_user)):
    request_data = request.model_dump()
    request_data["user_id"] = current_user["id"]
    query = work_requests.insert().values(**request_data)
    request_id = await database.execute(query)
    return {"message": "Заявка на работу успешно создана!", "request_id": request_id}

@api_router.get("/work-requests")
async def get_work_requests(city_id: Optional[int] = None, specialization: Optional[str] = None):
    query = work_requests.select()
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    if specialization is not None:
        query = query.where(work_requests.c.specialization == specialization)
    requests = await database.fetch_all(query)
    return requests

# --- Измененная функция ---
@api_router.post("/machinery-requests")
async def create_machinery_request(
    request: MachineryRequestCreate,
    current_user: dict = Depends(get_current_user)
):
    request_data = request.model_dump()
    request_data["user_id"] = current_user["id"]
    query = machinery_requests.insert().values(**request_data)
    request_id = await database.execute(query)
    return {"message": "Заявка на спецтехнику успешно создана!", "request_id": request_id}
# --- Конец измененной функции ---

@api_router.get("/machinery-requests")
async def get_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select()
    if city_id is not None:
        query = query.where(machinery_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return requests

@api_router.post("/tool-requests")
async def create_tool_request(request: ToolRequestCreate, current_user: dict = Depends(get_current_user)):
    request_data = request.model_dump()
    request_data["user_id"] = current_user["id"]
    query = tool_requests.insert().values(**request_data)
    request_id = await database.execute(query)
    return {"message": "Заявка на инструмент успешно создана!", "request_id": request_id}

@api_router.get("/tool-requests")
async def get_tool_requests(city_id: Optional[int] = None):
    query = tool_requests.select()
    if city_id is not None:
        query = query.where(tool_requests.c.city_id == city_id)
    requests = await database.fetch_all(query)
    return requests

@api_router.post("/material-ads")
async def create_material_ad(ad: MaterialAdCreate, current_user: dict = Depends(get_current_user)):
    ad_data = ad.model_dump()
    ad_data["user_id"] = current_user["id"]
    query = material_ads.insert().values(**ad_data)
    ad_id = await database.execute(query)
    return {"message": "Объявление о материалах успешно создано!", "ad_id": ad_id}

@api_router.get("/material-ads")
async def get_material_ads(city_id: Optional[int] = None):
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

app.include_router(api_router)

# Подключаем папку "static" для раздачи статических файлов
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/")
async def serve_index():
    return HTMLResponse(content=open("index.html", encoding="utf-8").read(), status_code=200)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)