import json
import uvicorn
import databases
from passlib.context import CryptContext
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# Import the database tables and engine
from database import users, work_requests, machinery_requests, tool_requests, material_ads, metadata, engine, DATABASE_URL

# Database connection
database = databases.Database(DATABASE_URL)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pydantic models for data validation
class UserCreate(BaseModel):
    phone: str
    password: str
    user_name: str
    user_type: str
    city: str
    specialization: Optional[str] = None

class UserUpdate(BaseModel):
    specialization: str

class RequestBase(BaseModel):
    description: str
    city: str
    customer_phone: str
    status: str

class WorkRequestCreate(RequestBase):
    specialization: str
    address: Optional[str] = None

class MachineryRequestCreate(RequestBase):
    machinery_type: str
    address: str
    min_order_4h: bool
    is_preorder: bool
    preorder_date: Optional[str] = None

class ToolRequestCreate(BaseModel):
    tools_list: List[str]
    rent_start_date: str
    rent_end_date: str
    delivery: bool
    delivery_address: Optional[str] = None
    description: Optional[str] = None
    city: str
    customer_phone: str

class MaterialAdCreate(BaseModel):
    materials: str
    description: str
    city: str
    seller_phone: str

app = FastAPI(title="СМЗ.РФ API")

# CORS middleware to allow the HTML file to access the server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, this should be a specific URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect to the database on startup
@app.on_event("startup")
async def startup():
    # Create tables if they don't exist
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
        user_name=user.user_name,
        user_type=user.user_type,
        city=user.city,
        specialization=user.specialization
    )
    last_record_id = await database.execute(insert_query)
    return {
        "id": last_record_id,
        "phone": user.phone,
        "user_name": user.user_name,
        "user_type": user.user_type,
        "city": user.city,
        "specialization": user.specialization
    }

# User Login
@app.post("/api/login")
async def login_user(form_data: dict):
    phone = form_data.get("phone")
    password = form_data.get("password")
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
    # Fetch and return the updated user object
    updated_user = await database.fetch_one(users.select().where(users.c.id == user_id))
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return updated_user

# Create Work Request
@app.post("/api/work-requests", status_code=status.HTTP_201_CREATED)
async def create_work_request(request: WorkRequestCreate):
    insert_query = work_requests.insert().values(**request.dict(), status='open', created_at=datetime.utcnow())
    last_record_id = await database.execute(insert_query)
    return {**request.dict(), "id": last_record_id, "status": 'open'}

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

# Create Machinery Request
@app.post("/api/machinery-requests", status_code=status.HTTP_201_CREATED)
async def create_machinery_request(request: MachineryRequestCreate):
    insert_query = machinery_requests.insert().values(**request.dict(), status='open', created_at=datetime.utcnow())
    last_record_id = await database.execute(insert_query)
    return {**request.dict(), "id": last_record_id, "status": 'open'}

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
    # Convert tools_list to JSON string for storage
    values = request.dict()
    values['tools_list'] = json.dumps(request.tools_list)
    insert_query = tool_requests.insert().values(**values, created_at=datetime.utcnow())
    last_record_id = await database.execute(insert_query)
    return {**request.dict(), "id": last_record_id}

# Get Tool Requests
@app.get("/api/tool-requests")
async def get_tool_requests(city: Optional[str] = None, customer_phone: Optional[str] = None):
    query = tool_requests.select()
    if city:
        query = query.where(tool_requests.c.city == city)
    if customer_phone:
        query = query.where(tool_requests.c.customer_phone == customer_phone)
    results = await database.fetch_all(query)
    
    # Convert JSON string back to list
    for result in results:
        if result['tools_list']:
            result = dict(result)
            result['tools_list'] = json.loads(result['tools_list'])
    return results

# Create Material Ad
@app.post("/api/material-ads", status_code=status.HTTP_201_CREATED)
async def create_material_ad(ad: MaterialAdCreate):
    insert_query = material_ads.insert().values(**ad.dict(), created_at=datetime.utcnow())
    last_record_id = await database.execute(insert_query)
    return {**ad.dict(), "id": last_record_id}

# Get Material Ads
@app.get("/api/material-ads")
async def get_material_ads(city: Optional[str] = None, seller_phone: Optional[str] = None):
    query = material_ads.select()
    if city:
        query = query.where(material_ads.c.city == city)
    if seller_phone:
        query = query.where(material_ads.c.seller_phone == seller_phone)
    return await database.fetch_all(query)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
