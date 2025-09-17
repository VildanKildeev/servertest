import os
from database import metadata, engine

def create_tables():
    print("Создание таблиц...")
    try:
        metadata.create_all(engine)
        print("Таблицы успешно созданы!")
    except Exception as e:
        print(f"Ошибка при создании таблиц: {e}")

if __name__ == "__main__":
    create_tables()