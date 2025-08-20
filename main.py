# main.py

import os
import sqlite3
from datetime import datetime

from fastapi import FastAPI, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
import databases
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    DateTime,
)

# === Настройка базы данных ===
DATABASE_URL = "sqlite:///./db.sqlite3"
database = databases.Database(DATABASE_URL)
metadata = MetaData()

# === Определение таблиц ===
tool_requests = Table(
    "tool_requests",
    metadata,
    Column("id", Integer, primary_key=True, index=True),
    Column("name", String),
    Column("phone", String),
    Column("tool", String),
    Column("date", String),
)

material_ads = Table(
    "material_ads",
    metadata,
    Column("id", Integer, primary_key=True, index=True),
    Column("name", String),
    Column("phone", String),
    Column("material", String),
    Column("amount", String),
    Column("date", String),
)

# === Создание таблиц при старте (если их нет) ===
def create_db_and_tables():
    if not os.path.exists("db.sqlite3"):
        print("Создаю базу данных и таблицы...")
        engine = create_engine("sqlite:///db.sqlite3")
        metadata.create_all(engine)
        print("База данных и таблицы созданы.")

# === FastAPI приложение ===
app = FastAPI(
    title="Tool and Material API",
    description="API для заявок на инструменты и объявлений о материалах",
    version="1.0.0",
)

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Меняй на нужные домены в продакшене
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Жизненный цикл приложения ===
@app.on_event("startup")
async def startup():
    await database.connect()
    create_db_and_tables()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# === Маршруты ===

@app.get("/")
def read_root():
    return {"message": "API работает. Используй /api/tool-requests или /api/material-ads"}

# --- Заявки на инструменты ---
@app.post("/api/tool-requests")
async def create_tool_request(
    name: str = Form(...),
    phone: str = Form(...),
    tool: str = Form(...),
):
    query = tool_requests.insert().values(
        name=name,
        phone=phone,
        tool=tool,
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, "status": "Заявка на инструмент создана"}

@app.get("/api/tool-requests")
async def get_tool_requests():
    query = tool_requests.select()
    return await database.fetch_all(query)

# --- Объявления о материалах ---
@app.post("/api/material-ads")
async def create_material_ad(
    name: str = Form(...),
    phone: str = Form(...),
    material: str = Form(...),
    amount: str = Form(...),
):
    query = material_ads.insert().values(
        name=name,
        phone=phone,
        material=material,
        amount=amount,
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    last_record_id = await database.execute(query)
    return {"id": last_record_id, "status": "Объявление о материале создано"}

@app.get("/api/material-ads")
async def get_material_ads():
    query = material_ads.select()
    return await database.fetch_all(query)

# --- Логин (пример) ---
@app.post("/api/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
):
    # Простой пример — в продакшене используй JWT и хеширование
    if username == "admin" and password == "12345":
        return {"message": "Успешный вход", "user": username}
    raise HTTPException(status_code=401, detail="Неверный логин или пароль")