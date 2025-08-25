import json
import uvicorn
import databases
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime

# Импорт базы данных
from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL

# Подключение к БД
database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="СМЗ.РФ API")

# Разрешаем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Подключение к БД ===
@app.on_event("startup")
async def startup():
    metadata.create_all(engine)
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# === Хеширование паролей ===
def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


# === Pydantic модели ===

class UserCreate(BaseModel):
    username: str
    password: str
    city_id: int

class LoginData(BaseModel):
    username: str
    password: str

class WorkRequestCreate(BaseModel):
    description: str
    budget: float
    contact_info: str
    city_id: int
    user_id: Optional[int] = None

class MachineryRequestCreate(BaseModel):
    machinery_type: str
    description: str
    budget: float
    contact_info: str
    city_id: int
    user_id: Optional[int] = None

class ToolRentalCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    city_id: int
    user_id: Optional[int] = None

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: str
    city_id: int
    user_id: Optional[int] = None


# === Аутентификация ===
async def get_current_user(token: str = Security(lambda x: x, scopes=[])):
    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    try:
        # Наш токен — fake_token_<user_id>
        if not token.startswith("fake_token_"):
            raise HTTPException(status_code=401, detail="Неверный токен")
        user_id = int(token.split("_")[-1])
        query = users.select().where(users.c.id == user_id)
        user = await database.fetch_one(query)
        if not user:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="Неверный токен")


# === Эндпоинты ===

# Список городов
@app.get("/cities")
async def get_cities():
    return [
        {"id": 1, "name": "Москва"},
        {"id": 2, "name": "Санкт-Петербург"},
        {"id": 3, "name": "Новосибирск"},
        {"id": 4, "name": "Екатеринбург"},
        {"id": 5, "name": "Казань"},
    ]


# Регистрация
@app.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate):
    query = users.select().where(users.c.username == user.username)
    existing = await database.fetch_one(query)
    if existing:
        raise HTTPException(status_code=409, detail="Пользователь с таким именем уже существует.")

    hashed_password = get_password_hash(user.password)
    insert_query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        city_id=user.city_id
    )
    user_id = await database.execute(insert_query)
    return {"message": "Пользователь успешно зарегистрирован.", "user_id": user_id}


# Вход
@app.post("/login")
async def login( LoginData):
    query = users.select().where(users.c.username == data.username)
    user = await database.fetch_one(query)
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")

    token = f"fake_token_{user['id']}"

    return {
        "access_token": token,
        "user_id": user["id"],
        "username": user["username"],
        "city_id": user["city_id"]
    }


# Профиль пользователя
@app.get("/users/{user_id}")
async def get_user(user_id: int, token: str = Security(get_current_user)):
    query = users.select().where(users.c.id == user_id)
    user = await database.fetch_one(query)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {
        "id": user["id"],
        "username": user["username"],
        "city_id": user["city_id"]
    }


# === Нанять мастера ===

@app.post("/work-requests", status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestCreate, user: dict = Depends(get_current_user)):
    insert_query = work_requests.insert().values(
        description=request.description,
        budget=request.budget,
        contact_info=request.contact_info,
        city_id=request.city_id,
        user_id=request.user_id or user["id"],
        created_at=datetime.utcnow()
    )
    request_id = await database.execute(insert_query)
    return {**request.dict(), "id": request_id}


@app.get("/work-requests")
async def get_work_requests(city_id: Optional[int] = None):
    query = work_requests.select()
    if city_id:
        query = query.where(work_requests.c.city_id == city_id)
    rows = await database.fetch_all(query)
    return [
        {
            "id": row["id"],
            "description": row["description"],
            "budget": row["budget"],
            "contact_info": row["contact_info"],
            "user_id": row["user_id"],
            "city_id": row["city_id"],
            "timestamp": row["created_at"].isoformat()
        }
        for row in rows
    ]

@app.post("/work-requests/{request_id}/take")
async def take_work_request(request_id: int, data: dict, user: dict = Depends(get_current_user)):
    # Проверим, существует ли запрос
    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)
    if not request:
        raise HTTPException(status_code=404, detail="Запрос не найден")

    # Можно обновить статус, добавить исполнителя и т.д.
    return {"message": f"Вы взяли заказ на работу №{request_id}"}


# === Аренда спецтехники ===

@app.post("/machinery-requests", status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestCreate, user: dict = Depends(get_current_user)):
    insert_query = machinery_requests.insert().values(
        machinery_type=request.machinery_type,
        description=request.description,
        budget=request.budget,
        contact_info=request.contact_info,
        city_id=request.city_id,
        user_id=request.user_id or user["id"],
        created_at=datetime.utcnow()
    )
    request_id = await database.execute(insert_query)
    return {**request.dict(), "id": request_id}


@app.get("/machinery-requests")
async def get_machinery_requests(city_id: Optional[int] = None):
    query = machinery_requests.select()
    if city_id:
        query = query.where(machinery_requests.c.city_id == city_id)
    rows = await database.fetch_all(query)
    return [
        {
            "id": row["id"],
            "machinery_type": row["machinery_type"],
            "description": row["description"],
            "budget": row["budget"],
            "contact_info": row["contact_info"],
            "user_id": row["user_id"],
            "city_id": row["city_id"],
            "timestamp": row["created_at"].isoformat()
        }
        for row in rows
    ]

@app.post("/machinery-requests/{request_id}/take")
async def take_machinery_request(request_id: int, data: dict, user: dict = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.id == request_id)
    request = await database.fetch_one(query)
    if not request:
        raise HTTPException(status_code=404, detail="Запрос не найден")

    return {"message": f"Вы взяли заказ на спецтехнику №{request_id}"}


# === Продать материалы ===
@app.post("/material-ads", status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad: MaterialAdCreate, user: dict = Depends(get_current_user)):
    insert_query = material_ads.insert().values(
        material_type=ad.material_type,
        description=ad.description,
        price=ad.price,
        contact_info=ad.contact_info,
        city_id=ad.city_id,
        user_id=ad.user_id or user["id"],
        created_at=datetime.utcnow()
    )
    ad_id = await database.execute(insert_query)
    return {**ad.dict(), "id": ad_id}

@app.get("/material-ads")
async def get_material_ads(city_id: Optional[int] = None):
    query = material_ads.select()
    if city_id:
        query = query.where(material_ads.c.city_id == city_id)
    rows = await database.fetch_all(query)
    return [
        {
            "id": row["id"],
            "material_type": row["material_type"],
            "description": row["description"],
            "price": row["price"],
            "contact_info": row["contact_info"],
            "user_id": row["user_id"],
            "city_id": row["city_id"],
            "timestamp": row["created_at"].isoformat()
        }
        for row in rows
    ]


# === Аренда инструмента ===
@app.post("/tool-rentals", status_code=status.HTTP_201_CREATED)
async def create_tool_rental(tool: ToolRentalCreate, user: dict = Depends(get_current_user)):
    insert_query = tool_requests.insert().values(
        tool_name=tool.tool_name,
        description=tool.description,
        rental_price=tool.rental_price,
        contact_info=tool.contact_info,
        city_id=tool.city_id,
        user_id=tool.user_id or user["id"],
        created_at=datetime.utcnow()
    )
    tool_id = await database.execute(insert_query)
    return {**tool.dict(), "id": tool_id}

@app.get("/tool-rentals")
async def get_tool_rentals(city_id: Optional[int] = None):
    query = tool_requests.select()
    if city_id:
        query = query.where(tool_requests.c.city_id == city_id)
    rows = await database.fetch_all(query)
    return [
        {
            "id": row["id"],
            "tool_name": row["tool_name"],
            "description": row["description"],
            "rental_price": row["rental_price"],
            "contact_info": row["contact_info"],
            "user_id": row["user_id"],
            "city_id": row["city_id"],
            "timestamp": row["created_at"].isoformat()
        }
        for row in rows
    ]


# Запуск
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)