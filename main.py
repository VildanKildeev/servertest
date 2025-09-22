import json
import uvicorn
import databases
from jose import jwt, JWTError
from datetime import timedelta, datetime, date
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Depends, APIRouter, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy import exc
from sqlalchemy.orm import relationship

import os
from dotenv import load_dotenv

# --- Database setup ---
# Импортируем все таблицы и метаданные из файла database.py
from database import metadata, engine, users, work_requests, machinery_requests, tool_requests, material_ads, cities

load_dotenv()

# Инициализация базы данных
DATABASE_URL = os.environ.get("DATABASE_URL")
database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Настройки для токенов
SECRET_KEY = os.environ.get("SECRET_KEY", "your-super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

app = FastAPI(title="СМЗ.РФ API")
api_router = APIRouter(prefix="/api")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    # Создаем все таблицы при запуске приложения, используя метаданные из database.py
    metadata.create_all(engine)
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
    is_premium: Optional[bool] = False

class UserCreate(UserBase):
    password: str

class UserPublic(UserBase):
    id: int
    created_at: Optional[datetime] = None

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
    specialization: Optional[str] = None
    
class WorkRequestInDB(WorkRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    executor_id: Optional[int] = None
    city_id: int
    is_premium: Optional[bool] = False

class MachineryRequestCreate(BaseModel):
    machinery_type: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    
class MachineryRequestInDB(MachineryRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    city_id: int

class ToolRequestCreate(BaseModel):
    tool_name: str
    description: Optional[str] = None
    rental_price: float
    contact_info: str
    count: Optional[int] = None
    rental_start_date: Optional[date] = None
    rental_end_date: Optional[date] = None
    # НОВЫЕ ПОЛЯ:
    has_delivery: Optional[bool] = False
    delivery_address: Optional[str] = None

class ToolRequestInDB(ToolRequestCreate):
    id: int
    user_id: int
    created_at: datetime
    city_id: int
    # НОВЫЕ ПОЛЯ:
    has_delivery: Optional[bool] = False
    delivery_address: Optional[str] = None

class MaterialAdCreate(BaseModel):
    material_type: str
    description: Optional[str] = None
    price: float
    contact_info: Optional[str] = None

class MaterialAdInDB(MaterialAdCreate):
    id: int
    user_id: int
    created_at: datetime
    city_id: int

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
    if current_user:
        data_to_insert["user_id"] = current_user.id
        data_to_insert["city_id"] = current_user.city_id
    
    if "rental_start_date" in data_to_insert and isinstance(data_to_insert["rental_start_date"], str):
        data_to_insert["rental_start_date"] = datetime.strptime(data_to_insert["rental_start_date"], '%Y-%m-%d').date()
    if "rental_end_date" in data_to_insert and isinstance(data_to_insert["rental_end_date"], str):
        data_to_insert["rental_end_date"] = datetime.strptime(data_to_insert["rental_end_date"], '%Y-%m-%d').date()

    try:
        query = table.insert().values(**data_to_insert)
        last_record_id = await database.execute(query)
        new_record_data = {
            "id": last_record_id,
            "created_at": datetime.now(),
            **data_to_insert
        }
        return response_model(**new_record_data)
    except exc.IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"Ошибка при создании записи: {str(e)}")

# =======================================================
#               МАРШРУТЫ API
# =======================================================

@api_router.get("/create-tables")
async def create_tables():
    try:
        metadata.create_all(engine)
        return {"message": "Таблицы успешно созданы."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при создании таблиц: {str(e)}")

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
        "is_premium": user.is_premium
    }
    
    return await create_record_and_return(
        table=users,
        data_to_insert=data_to_insert,
        response_model=UserPublic
    )

@api_router.get("/users/me", response_model=UserPublic)
async def read_users_me(current_user: UserInDB = Depends(get_current_user)):
    user_data = current_user.model_dump()
    return UserPublic(**user_data)

@api_router.put("/users/update-specialization")
async def update_user_specialization(specialization: str, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только Исполнители могут обновлять специализацию.")

    query = users.update().where(users.c.id == current_user.id).values(specialization=specialization)
    await database.execute(query)
    return {"message": "Специализация успешно обновлена."}

@api_router.post("/subscribe")
async def subscribe_user(current_user: UserInDB = Depends(get_current_user)):
    if current_user.is_premium:
        raise HTTPException(status_code=400, detail="У вас уже есть премиум-подписка.")
    
    query = users.update().where(users.c.id == current_user.id).values(is_premium=True)
    await database.execute(query)
    
    return {"message": "Премиум-подписка успешно активирована!"}

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
    data_to_insert["is_premium"] = current_user.is_premium
    
    return await create_record_and_return(
        table=work_requests,
        data_to_insert=data_to_insert,
        response_model=WorkRequestInDB,
        current_user=current_user
    )

@api_router.get("/work-requests", response_model=List[WorkRequestInDB])
async def read_work_requests(city_id: Optional[int] = None):
    query = work_requests.select().where(work_requests.c.executor_id.is_(None))
    if city_id is not None:
        query = query.where(work_requests.c.city_id == city_id)
    
    requests = await database.fetch_all(query.order_by(work_requests.c.is_premium.desc()))
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
    if data_to_insert.get("rental_start_date"):
        data_to_insert["rental_start_date"] = date.fromisoformat(str(data_to_insert["rental_start_date"]))
    if data_to_insert.get("rental_end_date"):
        data_to_insert["rental_end_date"] = date.fromisoformat(str(data_to_insert["rental_end_date"]))
    
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
    return [MaterialAdInDB(**r._mapping) for r in ads]

@api_router.post("/work-requests/{request_id}/accept", response_model=WorkRequestInDB)
async def accept_work_request(request_id: int, current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_type != "ИСПОЛНИТЕЛЬ":
        raise HTTPException(status_code=403, detail="Только Исполнители могут принимать заявки.")

    if not current_user.specialization:
        raise HTTPException(status_code=400, detail="Для принятия заявки необходимо указать вашу специализацию.")

    query = work_requests.select().where(work_requests.c.id == request_id)
    request = await database.fetch_one(query)

    if not request:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    if request.executor_id is not None:
        raise HTTPException(status_code=400, detail="Эта заявка уже принята другим исполнителем.")
    
    update_query = work_requests.update().where(work_requests.c.id == request_id).values(executor_id=current_user.id)
    await database.execute(update_query)

    return WorkRequestInDB(**request._mapping)

@api_router.get("/cities")
async def get_cities_from_db():
    query = cities.select()
    city_list = await database.fetch_all(query)
    return [{"id": r._mapping["id"], "name": r._mapping["name"]} for r in city_list]


@api_router.get("/specializations")
async def get_specializations():
    specializations = [\
        "Отделочник", "Сантехник", "Электрик", "Мастер по мебели", "Мастер на час", "Уборка", "Проектирование"\
    ]
    return specializations

@api_router.get("/machinery-types")
async def get_machinery_types():
    machinery_types = [\
        "Экскаватор", "Бульдозер", "Автокран", "Самосвал", "Грейдер", "Погрузчик", "Каток", "Трактор", "Миксер"\
    ]
    return machinery_types

@api_router.get("/tools-list")
async def get_tools_list():
    tools_list = [
        "Виброплиты", "Вибротрамбовки", "Резчики швов", "Бензорезы", "Воздуходувка", "Виброкатки", "Осветительные мачты",
        "Бензиновые отбойные молотки", "Дизельные генераторы", "Бензиновые генераторы", "Отбойные молотки", "Перфораторы",
        "Штроборезы", "Торцовочные пилы", "Монтажные пилы", "Циркулярные пилы", "Сабельные пилы", "УШМ", "Краскопульты",
        "Электрорубанки", "Электролобзики", "Шуруповерты", "Электропилы", "Гайковерты", "Строительные фены", "Ножницы по металлу",
        "Дрели электрические", "Заклепочники", "Реноватор", "Бензобур", "Триммер", "Бензопила", "Культиваторы и мотоблоки",
        "Газонокосилка", "Каток садовый", "Вертикуттер", "Аэратор", "Кусторез", "Измельчитель веток", "Дровокол", "Снегоуборочная машина",
        "Садовый пылесос - воздуходувка", "Садовая тележка", "Бензиновый опрыскиватель", "Виброрейка", "Бетономешалка", "Глубинный вибратор",
        "Миксер", "Оборудование для обогрева бетона", "Растворные емкости", "Инструмент для вязки арматуры", "Станок для резки арматуры",
        "Станки для гибки арматуры (Армогибы)", "Монолитные стойки", "Строительные леса", "Вышки тура", "Лестницы и стремянки",
        "Опалубка", "Сетка для строительных лесов", "Рукав для мусора", "Мозаично-шлифовальные машины", "Паркето-шлифовальные машины",
        "Затирочные машины по бетону", "Эксцентриковые шлифовальные машины", "Ленточно-шлифовальные машины", "Шлифовальные машины для стен",
        "Фрезеровальные машины по бетону", "Строгальные машины", "Дизельные компрессоры", "Электрические компрессоры", "Мотопомпы",
        "Погружные насосы", "Пароочиститель", "Промышленный пылесос", "Минимойка", "Роботы для уборки", "Поломоечная машина",
        "Сварочный аппарат", "Паяльник для полипропиленовых труб", "Паяльник для линолеума", "Аппарат для стыковки труб большого диаметра",
        "Детектор проводки", "Оптический нивелир", "Лазерный нивелир", "Лазерный уровень", "Толщиномер для бетона", "Дальномер",
        "Тепловизор", "Металлоискатель", "Склерометр", "Толщиномер лако-красочного покрытия", "Люксометр", "Влагомер", "Пирометр",
        "ТДС метр - солемер", "Дозиметр", "Тестер емкости АКБ", "Толщиномер для металла", "Мегаомметр", "Электрические тепловые пушки",
        "Газовые тепловые пушки", "Дизельные тепловые пушки", "Теплогенераторы", "Осушители воздуха", "Прогрев грунта", "Промышленные вентиляторы",
        "Парогенератор", "Бытовки", "Кран Пионер", "Кран Умелец", "Ручная таль", "Домкраты", "Тележки гидравлические", "Лебедки",
        "Коленчатый подъемник", "Фасадный подъемник", "Телескопический подъемник", "Ножничный подъемник", "Штабелер",
        "Установка алмазного бурения", "Сантехническое оборудование", "Окрасочный аппарат", "Кровельное оборудование",
        "Электромонтажный инструмент", "Резьбонарезной инструмент", "Газорезочное оборудование", "Инструмент для фальцевой кровли",
        "Растворные станции", "Труборезы", "Оборудование для получения лицензии МЧС", "Оборудование для работы с композитом",
        "Рейсмусовый станок", "Дрель на магнитной подошве", "Плиткорезы", "Отрезной станок", "Фрезер", "Камнерезные станки",
        "Экскаваторы", "Погрузчик", "Манипулятор", "Дорожные катки", "Самосвалы", "Автокран", "Автовышка", "Мусоровоз", "Илосос",
        "Канистра", "Монтажный пистолет", "Когти монтерские", "Прицепы", "Удлинители", "Трубогибы", "Стабилизатор напряжения",
        "Стеклодомкраты", "Динамометрический ключ", "Ручной инструмент", "Полезное", "Зарядные устройства"
    ]
    return tools_list

app.include_router(api_router)

# Mount static files
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)