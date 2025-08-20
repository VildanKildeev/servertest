import json
import uvicorn
import databases
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

# Import the database tables and engine
from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL

# Database connection
database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pydantic models for data validation, with corrected field names to match HTML
# Corrected models use aliases to map camelCase from JS to snake_case in Python
class UserCreate(BaseModel):
    phone: str
    password: str
    userName: str = Field(..., alias="user_name")
    userType: str = Field(..., alias="user_type")
    city: str
    specialization: Optional[str] = None

class UserUpdate(BaseModel):
    specialization: str

# Базовая модель для запросов
class RequestBase(BaseModel):
    description: str
    city: str
    customerPhone: str = Field(..., alias="customer_phone")
    
    class Config:
        populate_by_name = True

# Исправленная модель для запроса на работу (убран status)
class WorkRequestCreate(BaseModel):
    description: str
    city: str
    customerPhone: str = Field(..., alias="customer_phone")
    specialization: str
    address: Optional[str] = None

    class Config:
        populate_by_name = True

# Исправленная модель для запроса на спецтехнику (убран status)
class MachineryRequestCreate(BaseModel):
    machineryType: str = Field(..., alias="machinery_type")
    address: str
    minOrder4h: bool = Field(False, alias="min_order_4h")
    isPreorder: bool = Field(False, alias="is_preorder")
    preorderDate: Optional[str] = Field(None, alias="preorder_date")
    description: Optional[str] = None
    city: str
    customerPhone: str = Field(..., alias="customer_phone")

    class Config:
        populate_by_name = True

class ToolRequestCreate(BaseModel):
    toolList: List[str] = Field(..., alias="tools_list")
    rentStartDate: str = Field(..., alias="rent_start_date")
    rentEndDate: str = Field(..., alias="rent_end_date")
    delivery: bool
    deliveryAddress: Optional[str] = Field(None, alias="delivery_address")
    description: Optional[str] = None
    city: str
    customerPhone: str = Field(..., alias="customer_phone")

    class Config:
        populate_by_name = True

class MaterialAdCreate(BaseModel):
    materialsList: str = Field(..., alias="materials")
    description: str
    city: str
    sellerPhone: str = Field(..., alias="seller_phone")

    class Config:
        populate_by_name = True

app = FastAPI(title="СМЗ.РФ API")

# CORS middleware to allow the HTML file to access the server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to the database on startup
@app.on_event("startup")
async def startup():
    metadata.create_all(engine)
    await database.connect()

# Disconnect from the database on shutdown
@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# Helper function to hash passwords
def get_password_hash(password):
    return pwd_context.hash(password)

# Helper function to verify passwords
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# === API ENDPOINTS ===

# User Registration
@app.post("/api/register", status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate):
    query = users.select().where(users.c.phone == user.phone)
    existing_user = await database.fetch_one(query)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Пользователь с таким телефоном уже существует."}
        )
    hashed_password = get_password_hash(user.password)
    insert_query = users.insert().values(
        phone=user.phone,
        password_hash=hashed_password,
        user_name=user.userName,
        user_type=user.userType,
        city=user.city,
        specialization=user.specialization
    )
    last_record_id = await database.execute(insert_query)
    return {
        "id": last_record_id,
        "phone": user.phone,
        "user_name": user.userName,
        "user_type": user.userType,
        "city": user.city,
        "specialization": user.specialization
    }

# User Login
@app.post("/api/login")
async def login_user(phone: str = Form(...), password: str = Form(...)):
    if not phone or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Телефон и пароль обязательны.")
    
    query = users.select().where(users.c.phone == phone)
    user = await database.fetch_one(query)
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Неверный телефон или пароль"}
        )
    return {
        "id": user["id"],
        "user_name": user["user_name"],
        "user_type": user["user_type"],
        "phone": user["phone"],
        "city": user["city"],
        "specialization": user["specialization"]
    }

# Update User Profile (Specialization)
@app.patch("/api/users/{user_id}")
async def update_user(user_id: int, user_update: UserUpdate):
    query = users.update().where(users.c.id == user_id).values(specialization=user_update.specialization)
    await database.execute(query)
    updated_user = await database.fetch_one(users.select().where(users.c.id == user_id))
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user

# Create Work Request (Исправлено)
@app.post("/api/work-requests", status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestCreate):
    insert_query = work_requests.insert().values(
        **request.dict(by_alias=True), # Теперь не конфликтует со status
        status='open',
        created_at=datetime.utcnow()
    )
    last_record_id = await database.execute(insert_query)
    return {**request.dict(by_alias=True), "id": last_record_id, "status": 'open'}

# Get Work Requests
@app.get("/api/work-requests")
async def get_work_requests(city: Optional[str] = None, status: Optional[str] = None, specialization: Optional[str] = None, customer_phone: Optional[str] = None):
    query = work_requests.select()
    if city:
        query = query.where(work_requests.c.city == city)
    if status:
        query = query.where(work_requests.c.status == status)
    if specialization:
        query = query.where(work_requests.c.specialization == specialization)
    if customer_phone:
        query = query.where(work_requests.c.customer_phone == customer_phone)
    return await database.fetch_all(query)

# Create Machinery Request (Исправлено)
@app.post("/api/machinery-requests", status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestCreate):
    insert_query = machinery_requests.insert().values(
        **request.dict(by_alias=True), # Теперь не конфликтует со status
        status='open',
        created_at=datetime.utcnow()
    )
    last_record_id = await database.execute(insert_query)
    return {**request.dict(by_alias=True), "id": last_record_id, "status": 'open'}

# Get Machinery Requests
@app.get("/api/machinery-requests")
async def get_machinery_requests(city: Optional[str] = None, status: Optional[str] = None, customer_phone: Optional[str] = None):
    query = machinery_requests.select()
    if city:
        query = query.where(machinery_requests.c.city == city)
    if status:
        query = query.where(machinery_requests.c.status == status)
    if customer_phone:
        query = query.where(machinery_requests.c.customer_phone == customer_phone)
    return await database.fetch_all(query)

# Create Tool Request
@app.post("/api/tool-requests", status_code=status.HTTP_201_CREATED)
async def create_tool_request(request: ToolRequestCreate):
    insert_query = tool_requests.insert().values(
        tools_list=json.dumps(request.toolList),
        rent_start_date=request.rentStartDate,
        rent_end_date=request.rentEndDate,
        delivery=request.delivery,
        delivery_address=request.deliveryAddress,
        description=request.description,
        city=request.city,
        customer_phone=request.customerPhone,
        created_at=datetime.utcnow()
    )
    last_record_id = await database.execute(insert_query)
    return {**request.dict(by_alias=True), "id": last_record_id, "status": 'open'}

# Create Material Ad
@app.post("/api/material-ads", status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad: MaterialAdCreate):
    insert_query = material_ads.insert().values(
        materials=ad.materialsList,
        description=ad.description,
        city=ad.city,
        seller_phone=ad.sellerPhone,
        created_at=datetime.utcnow()
    )
    last_record_id = await database.execute(insert_query)
    return {**ad.dict(by_alias=True), "id": last_record_id}

# Get Material Ads
@app.get("/api/material-ads")
async def get_material_ads():
    query = material_ads.select()
    return await database.fetch_all(query)