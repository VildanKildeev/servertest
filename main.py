import json
import uvicorn
import databases
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

# Импортируем базу данных
from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL

# Подключение к БД
database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="СМЗ.РФ API")

# Создаем роутер с префиксом /api
api_router = APIRouter(prefix="/api")

# Разрешаем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение к БД
@app.on_event("startup")
async def startup():
    # Удаляем и создаем таблицы, чтобы синхронизировать схему БД с кодом
    metadata.drop_all(engine)
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
    username: str # Номер телефона
    password: str
    city_id: int
    user_name: str
    user_type: str
    specialization: Optional[str] = None

class LoginData(BaseModel):
    username: str # Номер телефона
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

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
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


# === Аутентификация ===
async def get_current_user(authorization: str = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация (Bearer Token)")
    token = authorization.split(" ")[1]
    
    if not token or not token.startswith("fake_token_"):
        raise HTTPException(status_code=401, detail="Неверный формат токена")
    try:
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
    
# Список специализаций
@app.get("/specializations")
async def get_specializations():
    return [
        {"id": 1, "name": "Электрик"},
        {"id": 2, "name": "Сантехник"},
        {"id": 3, "name": "Маляр-штукатур"},
        {"id": 4, "name": "Плотник"},
        {"id": 5, "name": "Кровельщик"},
        {"id": 6, "name": "Сварщик"},
        {"id": 7, "name": "Универсальный мастер"}
    ]

# Регистрация
@api_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate):
    query = users.select().where(users.c.username == user.username)
    existing = await database.fetch_one(query)
    if existing:
        raise HTTPException(status_code=409, detail="Пользователь с таким номером уже существует.")

    hashed_password = get_password_hash(user.password)
    insert_query = users.insert().values(
        username=user.username,
        password_hash=hashed_password,
        city_id=user.city_id,
        user_name=user.user_name,
        user_type=user.user_type,
        specialization=user.specialization
    )
    user_id = await database.execute(insert_query)
    return {"message": "Пользователь успешно зарегистрирован.", "user_id": user_id}


# Вход
@api_router.post("/login")
async def login(data: LoginData):
    query = users.select().where(users.c.username == data.username)
    user = await database.fetch_one(query)
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный номер пользователя или пароль")

    token = f"fake_token_{user['id']}"

    return {
        "access_token": token,
        "user_id": user["id"],
        "username": user["username"],
        "user_name": user["user_name"],
        "user_type": user["user_type"],
        "specialization": user.get("specialization"),
        "city_id": user["city_id"]
    }


# Профиль пользователя
@api_router.get("/users/{user_id}")
async def get_user(user_id: int, user: dict = Depends(get_current_user)):
    if user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    cities = await get_cities()
    city_name = next((c["name"] for c in cities if c["id"] == user["city_id"]), "Неизвестен")

    return {
        "id": user["id"],
        "username": user["username"],
        "user_name": user["user_name"],
        "user_type": user["user_type"],
        "specialization": user.get("specialization"),
        "city_id": user["city_id"],
        "city_name": city_name
    }


# === Нанять мастера ===
@api_router.post("/work-requests", status_code=status.HTTP_201_CREATED)
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
    return {**request.dict(), "id": request_id, "timestamp": datetime.utcnow().isoformat()}


@api_router.get("/work-requests")
async def get_work_requests(city_id: int = None):
    query = work_requests.select()
    if city_id:
        query = query.where(work_requests.c.city_id == city_id)
    query = query.order_by(work_requests.c.created_at.desc()) 
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


# === Аренда спецтехники ===
@api_router.post("/machinery-requests", status_code=status.HTTP_201_CREATED)
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
    return {**request.dict(), "id": request_id, "timestamp": datetime.utcnow().isoformat()}


@api_router.get("/machinery-requests")
async def get_machinery_requests(city_id: int = None):
    query = machinery_requests.select()
    if city_id:
        query = query.where(machinery_requests.c.city_id == city_id)
    query = query.order_by(machinery_requests.c.created_at.desc()) 
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


# === Продать материалы ===
@api_router.post("/material-ads", status_code=status.HTTP_201_CREATED)
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
    return {**ad.dict(), "id": ad_id, "timestamp": datetime.utcnow().isoformat()}


@api_router.get("/material-ads")
async def get_material_ads(city_id: int = None):
    query = material_ads.select()
    if city_id:
        query = query.where(material_ads.c.city_id == city_id)
    query = query.order_by(material_ads.c.created_at.desc())
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
@api_router.post("/tool-rentals", status_code=status.HTTP_201_CREATED)
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
    return {**tool.dict(), "id": tool_id, "timestamp": datetime.utcnow().isoformat()}


@api_router.get("/tool-rentals")
async def get_tool_rentals(city_id: int = None):
    query = tool_requests.select()
    if city_id:
        query = query.where(tool_requests.c.city_id == city_id)
    query = query.order_by(tool_requests.c.created_at.desc())
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


# === Взять заказ (Take Order) - заглушки ===
@api_router.post("/work-requests/{request_id}/take")
async def take_work_request(request_id: int, user: dict = Depends(get_current_user)):
    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)
    if not request:
        raise HTTPException(status_code=404, detail="Запрос не найден")

    return {"message": f"Вы взяли заказ на работу №{request_id}"}


@api_router.post("/machinery-requests/{request_id}/take")
async def take_machinery_request(request_id: int, user: dict = Depends(get_current_user)):
    query = machinery_requests.select().where(machinery_requests.c.id == request_id)
    request = await database.fetch_one(query)
    if not request:
        raise HTTPException(status_code=404, detail="Запрос не найден")

    return {"message": f"Вы взяли заказ на спецтехнику №{request_id}"}

# Подключаем роутер к основному приложению
app.include_router(api_router)

# Обслуживание HTML-файла
@app.get("/", response_class=HTMLResponse)
async def serve_html():
    return """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>СМЗ.РФ - Рабочие и спецтехника</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        /* Ваши стили */
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; display: flex; flex-direction: column; justify-content: flex-start; align-items: center; color: white; overflow: hidden; background: black; -webkit-tap-highlight-color: transparent; touch-action: manipulation; }
        .background-video { position: fixed; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; z-index: -2; }
        .selected-city { margin-top: 12px; font-size: 16px; color: #fff; text-align: center; display: flex; align-items: center; justify-content: center; gap: 5px; flex-wrap: wrap; }
        #changeCityButton { background: none; border: none; color: white; font-weight: bold; text-decoration: underline; cursor: pointer; font-size: 14px; padding: 6px 10px; border-radius: 6px; }
        .grid-container { margin-top: 20px; display: flex; flex-direction: column; align-items: center; gap: 12px; width: 90%; max-width: 400px; z-index: 10; }
        .grid-row { display: flex; width: 100%; gap: 12px; }
        .tile-btn { flex: 1; color: #333; background: #e0d6c8; border: 2px solid #c0b0a0; padding: 16px 8px; font-size: 15px; font-weight: bold; border-radius: 16px; cursor: pointer; transition: all 0.3s ease; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2); text-align: center; position: relative; overflow: hidden; min-height: 80px; display: flex; flex-direction: column; justify-content: center; text-shadow: none; }
        .tile-btn::after { content: ""; position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255, 255, 255, 0.1); border-radius: 16px; z-index: 0; pointer-events: none; }
        .tile-btn span { position: relative; z-index: 1; display: block; }
        .tile-btn small { font-size: 12px; opacity: 0.9; margin-top: 4px; }
        .tile-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4); }
        .navigation { position: fixed; bottom: 0; left: 0; width: 100%; background: rgba(216, 201, 183, 0.95); display: flex; justify-content: space-around; padding: 12px 0; z-index: 50; backdrop-filter: blur(10px); border-top: 1px solid #c0b0a0; }
        .nav-btn { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; background: none; border: none; cursor: pointer; padding: 8px 16px; border-radius: 12px; transition: all 0.2s ease; background: #f5f0e6; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1); }
        .nav-btn span { font-size: 13px; color: #5a4a3a; }
        .nav-btn:hover { transform: translateY(-2px); box-shadow: 0 4px 10px rgba(0, 0, 0, 0.15); background: #e8dccf; }
        .modal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.95); display: none; justify-content: center; align-items: center; z-index: 300; opacity: 0; pointer-events: none; transition: opacity 0.3s ease; }
        .modal.active { display: flex; opacity: 1; pointer-events: all; }
        .modal-content { background: #d8c9b7; border: 2px solid #c0b0a0; border-radius: 16px; padding: 20px; width: 90%; max-width: 420px; text-align: center; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3); display: flex; flex-direction: column; align-items: center; position: relative; overflow: hidden; transform: scale(0.9); opacity: 0; transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275); color: #333; max-height: 90vh; overflow-y: auto; }
        .modal.active .modal-content { transform: scale(1); opacity: 1; }
        .modal-title { font-size: 20px; margin-bottom: 16px; color: #5a4a3a; text-align: center; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.1); }
        .search-container { width: 90%; position: relative; margin-bottom: 12px; }
        .search-container input { width: 100%; padding: 10px 10px 10px 36px; border: 1px solid #c0b0a0; border-radius: 8px; font-size: 15px; background: #e8dccf; color: #333; outline: none; }
        .search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: #7d6b59; font-size: 16px; pointer-events: none; }
        .modal-buttons { display: flex; flex-direction: column; gap: 12px; width: 100%; align-items: center; margin-top: 10px; }
        .modal-button { color: #5a4a3a; border: 2px solid #5a4a3a; padding: 14px; font-size: 16px; font-weight: bold; border-radius: 10px; cursor: pointer; background: #f5f0e6; width: 90%; max-width: 300px; margin: 8px 0; transition: all 0.3s ease; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.1); }
        .modal-button:hover { background: #e0d6c8; transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15); }
        .close-modal { position: absolute; top: 12px; right: 12px; font-size: 24px; color: #5a4a3a; cursor: pointer; background: none; border: none; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; z-index: 10; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.2); }
        #authModal, #registerModal, #profilePage, #requestFormPage, #takeOrderPage, #myRequestsPage, #machineryFormPage, #toolsFormPage, #chatPage, #marketplacePage, #materialsFormPage { display: none; flex-direction: column; align-items: center; width: 100%; height: 100vh; background: #d8c9b7; position: fixed; top: 0; left: 0; z-index: 200; padding: 20px 16px; overflow-y: auto; color: #333; }
        #buttonContainer { display: none; }
        .auth-header { font-size: 24px; color: #5a4a3a; text-align: center; margin-bottom: 20px; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.2); }
        .form-container { background: #e8dccf; border: 1px solid #c0b0a0; border-radius: 12px; padding: 20px; width: 90%; max-width: 500px; margin: 0 auto; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
        .form-group { width: 100%; margin-bottom: 16px; text-align: left; }
        .form-group label { display: block; margin-bottom: 6px; color: #7d6b59; font-size: 14px; }
        .form-group input, .form-group select, .form-group textarea { width: 100%; padding: 12px; border: 1px solid #c0b0a0; border-radius: 8px; background: #e8dccf; color: #333; font-size: 16px; }
        .auth-button { background: #4caf50; color: white; border: none; padding: 14px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; width: 100%; margin-top: 10px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2); }
        .profile-header { font-size: 20px; color: #5a4a3a; text-align: center; margin-bottom: 20px; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.2); }
        .profile-card { background: #e8dccf; border: 1px solid #c0b0a0; border-radius: 12px; padding: 16px; width: 90%; max-width: 400px; margin-bottom: 16px; color: #333; text-align: left; box-shadow: 0 4-box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
        .profile-card strong { color: #7d6b59; }
        .profile-button { background: #4caf50; color: white; border: none; padding: 12px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; width: 90%; max-width: 400px; margin-top: 10px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); }
        .logout-button { background: #f44336; color: white; border: none; padding: 12px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; width: 90%; max-width: 400px; margin-top: 10px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); }
        .subscription-info { background: #e8dccf; border: 1px solid #c0b0a0; border-radius: 12px; padding: 16px; width: 90%; max-width: 400px; margin-bottom: 16px; color: #333; text-align: left; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
        .subscription-info h3 { color: #5a4a3a; margin-bottom: 12px; text-align: center; }
        .subscription-status { font-weight: bold; color: #d4380d; }
        .subscription-status.active { color: #4caf50; }
        .subscription-button { background: #4caf50; color: white; border: none; padding: 12px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; width: 100%; margin-top: 10px; transition: background-color 0.3s; }
        .subscription-button:disabled { background-color: #a5d6a7; cursor: not-allowed; }
        .form-title { text-align: center; color: #5a4a3a; margin-bottom: 20px; font-size: 20px; }
        .checkbox-group { display: flex; align-items: center; gap: 10px; margin-bottom: 15px; }
        .checkbox-group input[type="checkbox"] { width: auto; }
        .submit-button { background: #4caf50; color: white; border: none; padding: 14px; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; width: 100%; margin-top: 10px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2); }
        .back-button { margin-top: 20px; color: #7d6b59; font-size: 15px; text-decoration: underline; cursor: pointer; display: block; text-align: center; }
        .orders-header, .requests-header, .marketplace-header { text-align: center; color: #5a4a3a; margin-bottom: 20px; font-size: 20px; }
        .orders-list { width: 90%; max-width: 500px; margin: 0 auto; }
        .order-card, .request-card, .post-card { background: #e8dccf; border: 1px solid #c0b0a0; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); color: #333; }
        .order-card strong, .request-card strong, .post-card strong { color: #5a4a3a; display: block; margin-bottom: 8px; font-size: 16px; }
        .order-card div, .request-card div, .post-card div { margin-bottom: 4px; font-size: 14px; color: #333; word-wrap: break-word; }
        .order-card div small, .request-card div small, .post-card div small { color: #7d6b59; }
        .order-card .subscription-notice { margin-top: 8px; padding: 8px; background-color: #f5e4cc; border-radius: 6px; font-size: 13px; color: #8c6c46; border: 1px dashed #c0b0a0; }
        .take-order-btn { background: #4caf50; color: white; border: none; padding: 10px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: bold; width: 100%; margin-top: 10px; }
        .no-orders { text-align: center; color: #7d6b59; padding: 20px; }
        .post-card .post-date { font-size: 12px; color: #7d6b59; text-align: right; margin-top: 10px; border-top: 1px solid #c0b0a0; padding-top: 8px; }
        .tool-item { display: flex; align-items: center; justify-content: space-between; padding: 10px; background: #e8dccf; border: 1px solid #c0b0a0; border-radius: 8px; margin-bottom: 10px; }
        .tool-item button { background: #d4380d; color: white; border: none; padding: 5px 10px; border-radius: 5px; cursor: pointer; }
    </style>
</head>
<body>
    <video autoplay muted loop class="background-video">
        <source src="https://telegram.org/file/8111409990/10b37f3868/240978" type="video/mp4">
        Ваш браузер не поддерживает видео.
    </video>
    <div class="selected-city">
        <span>Город: <span id="cityName">Не выбран</span></span>
        <button id="changeCityButton">Изменить</button>
    </div>
    <div class="grid-container" id="buttonContainer">
        <div class="grid-row">
            <button type="button" class="tile-btn" id="masterButton"><span>НАЙТИ МАСТЕРА</span><small>создать заявку</small></button>
            <button type="button" class="tile-btn" id="machineryButton"><span>АРЕНДА ТЕХНИКИ</span><small>создать заявку</small></button>
        </div>
        <div class="grid-row">
            <button type="button" class="tile-btn" id="toolsButton"><span>АРЕНДА ИНСТРУМЕНТА</span><small>создать заявку</small></button>
            <button type="button" class="tile-btn" id="sellMaterialsButton"><span>ПРОДАТЬ МАТЕРИАЛЫ</span><small>разместить объявление</small></button>
        </div>
        <div class="grid-row">
            <button type="button" class="tile-btn" id="marketplaceButton"><span>ДОСКА ОБЪЯВЛЕНИЙ</span><small>купить/продать</small></button>
            <button type="button" class="tile-btn" id="profileButton"><span>ЛИЧНЫЙ КАБИНЕТ</span><small>профиль и заявки</small></button>
        </div>
    </div>
    <div class="navigation">
        <button class="nav-btn" id="navMaster"><i class="fas fa-hammer"></i><span>Заказы</span></button>
        <button class="nav-btn" id="navCreate"><i class="fas fa-plus-circle"></i><span>Создать</span></button>
        <button class="nav-btn" id="navProfile"><i class="fas fa-user"></i><span>Профиль</span></button>
        <button class="nav-btn" id="navSubscription"><i class="fas fa-crown"></i><span>Подписка</span></button>
    </div>
    
    <div class="modal" id="cityModal"><div class="modal-content"><button class="close-modal">&times;</button><h2 class="modal-title">Выберите ваш город</h2><div class="search-container"><i class="fas fa-search search-icon"></i><input type="text" id="citySearch" placeholder="Поиск..."></div><div class="modal-buttons" id="cityButtons"></div></div></div>

    <div id="authModal"><h2 class="auth-header">Вход в аккаунт</h2><form id="authForm" class="form-container"><div class="form-group"><label for="userPhone">Номер телефона:</label><input type="tel" id="userPhone" placeholder="+7 (999) 999-99-99" required></div><div class="form-group"><label for="userPassword">Пароль:</label><input type="password" id="userPassword" placeholder="Введите пароль" required></div><button type="submit" class="auth-button">ВОЙТИ</button><a href="#" id="switchToRegister" class="back-button">У меня нет аккаунта (Регистрация)</a></form></div>
    
    <div id="registerModal" style="display: none;"><h2 class="auth-header">Регистрация</h2><form id="registerForm" class="form-container"><div class="form-group"><label for="regUserType">Я...</label><select id="regUserType" required><option value="">Выберите тип пользователя...</option><option value="ЗАКАЗЧИК">Заказчик</option><option value="ИСПОЛНИТЕЛЬ">Исполнитель</option><option value="ВЛАДЕЛЕЦ СПЕЦТЕХНИКИ">Владелец спецтехники</option></select></div><div class="form-group"><label for="regUserName">Мое имя:</label><input type="text" id="regUserName" placeholder="Введите ваше имя" required></div><div class="form-group"><label for="regUserPhone">Мой номер телефона:</label><input type="tel" id="regUserPhone" placeholder="+7 (999) 999-99-99" required></div><div class="form-group"><label for="regUserPassword">Придумайте пароль:</label><input type="password" id="regUserPassword" placeholder="Надежный пароль" required></div><div class="form-group" id="regSpecializationGroup" style="display: none;"><label for="regSpecializationSelect">Моя основная специализация:</label><select id="regSpecializationSelect"></select></div><button type="submit" class="auth-button">ЗАРЕГИСТРИРОВАТЬСЯ</button><a href="#" id="switchToLogin" class="back-button">У меня уже есть аккаунт (Войти)</a></form></div>

    <div id="profilePage">
        <h2 class="profile-header">Ваш профиль</h2>
        <div class="profile-card">
            <div><strong>Тип:</strong> <span id="profileType"></span></div>
            <div><strong>Имя:</strong> <span id="profileName"></span></div>
            <div><strong>Телефон:</strong> <span id="profilePhone"></span></div>
            <div><strong>Город:</strong> <span id="profileCity"></span></div>
            <div id="profileSpecializationDisplay" style="margin-top: 10px; display: none;"><strong>Специализация:</strong> <span id="profileSpecialization"></span></div>
        </div>
        <div class="form-container" id="specializationGroup" style="display: none; padding: 15px; margin-top: 0; max-width: 400px;">
            <div class="form-group" style="width: 100%; margin:0;">
                <label for="profileSpecializationSelect">Изменить специализацию:</label>
                <select id="profileSpecializationSelect" style="width: 100%; padding: 10px;"></select>
                <button type="button" id="saveSpecialization" class="auth-button" style="margin-top: 10px; width: 100%;">Сохранить</button>
            </div>
        </div>
        <div class="subscription-info">
            <h3>Подписка "Профи"</h3>
            <div>Статус: <span id="subscriptionStatus" class="subscription-status">Не активна</span></div>
            <div>Срок действия: <span id="subscriptionExpiry">-</span></div>
            <button class="subscription-button" id="subscriptionButton">Оформить подписку</button>
        </div>
        <button class="profile-button" id="myRequestsButton">Мои заявки</button>
        <button class="logout-button" id="logoutButton">ВЫЙТИ</button>
        <a href="#" class="back-button" id="backToMain">← Назад</a>
    </div>

    <div id="requestFormPage">
         <div class="form-container">
            <h2 class="form-title">Создать заявку на работы</h2>
            <form id="requestForm">
                <div class="form-group"><label for="workType">Тип работ:</label><select id="workType" required></select></div>
                <div class="checkbox-group"><input type="checkbox" id="visitCheckbox"><label for="visitCheckbox">Нужен выезд мастера на адрес</label></div>
                <div class="form-group" id="addressField" style="display: none;"><label for="workAddress">Адрес выполнения работ:</label><input type="text" id="workAddress" placeholder="Укажите адрес"></div>
                <div class="form-group"><label for="requestDescription">Подробное описание задачи:</label><textarea id="requestDescription" placeholder="Опишите детали заказа..." required></textarea></div>
                <div class="form-group"><label for="requestPhotos">Фотографии (необязательно):</label><input type="file" id="requestPhotos" accept="image/*" multiple></div>
                <button type="submit" class="submit-button">ОТПРАВИТЬ ЗАЯВКУ</button>
                <a href="#" class="back-button" id="backToMainFromRequest">← Назад</a>
            </form>
        </div>
    </div>
    
    <div id="machineryFormPage">
        <div class="form-container">
            <h2 class="form-title">Заявка на аренду спецтехники</h2>
            <form id="machineryForm">
                <div class="form-group"><label for="machineryType">Тип спецтехники:</label><select id="machineryType" required></select></div>
                <div class="form-group"><label for="machineryAddress">Адрес подачи техники:</label><input type="text" id="machineryAddress" placeholder="Укажите адрес" required></div>
                <div class="checkbox-group"><input type="checkbox" id="minOrderCheckbox"><label for="minOrderCheckbox">Минимальный заказ (4 часа)</label></div>
                <div class="checkbox-group"><input type="checkbox" id="preorderCheckbox"><label for="preorderCheckbox">Предварительный заказ</label></div>
                <div id="preorderFields" style="display: none;">
                    <div class="form-group"><label for="preorderDate">Дата и время:</label><input type="datetime-local" id="preorderDate"></div>
                </div>
                <div class="form-group"><label for="machineryDescription">Описание задачи:</label><textarea id="machineryDescription" placeholder="Дополнительная информация..."></textarea></div>
                <div class="form-group"><label for="machineryPhotos">Фотографии (необязательно):</label><input type="file" id="machineryPhotos" accept="image/*" multiple></div>
                <button type="submit" class="submit-button">ОТПРАВИТЬ ЗАЯВКУ</button>
                <a href="#" class="back-button" id="backToMainFromMachinery">← Назад</a>
            </form>
        </div>
    </div>

    <div id="toolsFormPage">
         <div class="form-container">
            <h2 class="form-title">Заявка на аренду инструмента</h2>
            <form id="toolsForm">
                <div class="form-group">
                    <label for="toolsSelect">Какой инструмент нужен?</label>
                    <select id="toolsSelect"></select>
                    <button type="button" id="addToolBtn" class="profile-button" style="margin-top: 10px;">Добавить в список</button>
                </div>
                <div id="selectedToolsList" style="margin: 15px 0;"></div>
                <div class="form-group"><label for="rentStartDate">Дата начала аренды:</label><input type="date" id="rentStartDate" required></div>
                <div class="form-group"><label for="rentEndDate">Дата окончания аренды:</label><input type="date" id="rentEndDate" required></div>
                <div class="checkbox-group"><input type="checkbox" id="deliveryCheckbox"><label for="deliveryCheckbox">Нужна доставка</label></div>
                <div class="form-group" id="deliveryAddressField" style="display: none;"><label for="deliveryAddress">Адрес доставки:</label><input type="text" id="deliveryAddress" placeholder="Укажите адрес доставки"></div>
                <div class="form-group"><label for="toolsDescription">Дополнительная информация:</label><textarea id="toolsDescription" placeholder="Например, нужен ли оператор..."></textarea></div>
                <button type="submit" class="submit-button">ОТПРАВИТЬ ЗАЯВКУ</button>
                <a href="#" class="back-button" id="backToMainFromTools">← Назад</a>
            </form>
        </div>
    </div>
    
    <div id="takeOrderPage"><h2 class="orders-header">Доступные заявки</h2><div class="orders-list" id="ordersList"></div><a href="#" class="back-button" id="backToMainFromTakeOrder">← Назад</a></div>
    <div id="myRequestsPage"><h2 class="requests-header">Мои заявки</h2><div class="orders-list" id="userRequestsList"></div><a href="#" class="back-button" id="backToProfileFromRequests">← Назад в профиль</a></div>
    
    <div id="materialsFormPage">
        <div class="form-container">
            <h2 class="form-title">Продать материалы</h2>
            <form id="materialsForm">
                <div class="form-group"><label for="materialsInput">Материал(ы):</label><input type="text" id="materialsInput" placeholder="Например: Кирпич, Цемент" required></div>
                <div class="form-group"><label for="materialsDescription">Описание (состояние, кол-во, цена):</label><textarea id="materialsDescription" placeholder="Осталось 100 кирпичей. Самовывоз." required></textarea></div>
                <button type="submit" class="submit-button">РАЗМЕСТИТЬ ОБЪЯВЛЕНИЕ</button>
                <a href="#" class="back-button" id="backToMainFromMaterials">← Назад</a>
            </form>
        </div>
    </div>
    
    <div id="marketplacePage">
        <h2 class="marketplace-header">Доска объявлений</h2>
        <div id="marketplacePosts" class="orders-list"></div>
        <a href="#" class="back-button" id="backToMainFromMarketplace">← Назад</a>
    </div>

    <div class="modal" id="paymentModal"><div class="modal-content"><button class="close-modal">&times;</button><h2 class="modal-title">Оформление подписки "Профи"</h2><p style="margin-bottom: 20px; text-align: center;">Стоимость: 299 руб./месяц</p><form id="paymentForm"><div class="form-group" style="width:100%;"><label for="cardNumber">Номер карты:</label><input type="text" id="cardNumber" placeholder="1234 5678 9012 3456" required></div><div style="display: flex; gap: 10px; margin-bottom: 15px; width:100%;"><div style="flex: 1; text-align: left;"><div style="color: #7d6b59; font-size: 14px; margin-bottom: 6px;">Срок</div><input type="text" id="cardExpiry" placeholder="MM/YY" required style="width: 100%; padding: 12px; border: 1px solid #c0b0a0; border-radius: 8px; background: #e8dccf; color: #333; font-size: 16px;"></div><div style="flex: 1; text-align: left;"><div style="color: #7d6b59; font-size: 14px; margin-bottom: 6px;">CVV</div><input type="text" id="cardCvv" placeholder="123" required style="width: 100%; padding: 12px; border: 1px solid #c0b0a0; border-radius: 8px; background: #e8dccf; color: #333; font-size: 16px;"></div></div><div class="form-group" style="width:100%;"><label for="cardHolder">Имя владельца:</label><input type="text" id="cardHolder" placeholder="Иван Иванов" required></div><button type="submit" class="subscription-button" id="paymentButton">ОПЛАТИТЬ</button></form></div></div> <script> // ======================================================================= // НАЧАЛО БЛОКА JAVASCRIPT // ======================================================================= // === ГЛАВНАЯ НАСТРОЙКА === const SERVER_URL = 'https://servertest2-0.onrender.com/api'; // === ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ === let currentUser = JSON.parse(localStorage.getItem('currentUser')) || null; let selectedCity = localStorage.getItem('selectedCity') || 'Москва'; // === СПИСКИ ДАННЫХ === const cities = ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань", "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону", "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград"]; const reqWork...
    """

# Запуск
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)