from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os

app = FastAPI(title="PACO ERP - Servidor Estable")

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELOS ---
class Ingredient(BaseModel):
    name: str
    stock: float
    unit: str

class OrderItem(BaseModel):
    nombre: str
    precio: float

class OrderUpdate(BaseModel):
    items: List[OrderItem]

# --- BASE DE DATOS TEMPORAL ---
db_ingredients = []
db_tables = [
    {"id": 1, "number": 1, "capacity": 4, "status": "Libre", "order": []},
    {"id": 2, "number": 2, "capacity": 2, "status": "Libre", "order": []}
]

# --- RUTAS DE LA API ---

@app.get("/ingredients")
def get_ingredients():
    return db_ingredients

@app.post("/ingredients")
def create_ingredient(item: Ingredient):
    try:
        if any(ing["name"].lower() == item.name.lower() for ing in db_ingredients):
            raise HTTPException(status_code=400, detail="Ya existe")
        db_ingredients.append(item.dict())
        return item
    except Exception as e:
        print(f"ERROR EN POST INGREDIENTS: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/ingredients/reduce")
def reduce_stock(name: str = Query(...), amount: float = Query(...)):
    for ing in db_ingredients:
        if ing["name"].lower() == name.lower():
            ing["stock"] -= amount
            return {"status": "success", "new_stock": ing["stock"]}
    raise HTTPException(status_code=404)

@app.get("/tables")
def get_tables():
    return db_tables

@app.put("/tables/{table_id}/status")
def update_table_status(table_id: int, status: str):
    for t in db_tables:
        if t["id"] == table_id:
            t["status"] = status
            if status == "Libre": t["order"] = []
            return t
    raise HTTPException(status_code=404)

@app.post("/tables/{table_id}/order")
def update_table_order(table_id: int, update: OrderUpdate):
    for t in db_tables:
        if t["id"] == table_id:
            t["order"] = [item.dict() for item in update.items]
            return {"status": "ok"}
    raise HTTPException(status_code=404)

# --- RUTA PARA EL HTML ---

@app.get("/")
def read_index():
    # Buscamos el archivo primero en la carpeta static, luego en la raíz
    paths = ["static/index.html", "index.html"]
    for path in paths:
        if os.path.exists(path):
            return FileResponse(path)
    
    return {"error": "No he encontrado el archivo index.html. Asegúrate de que esté en la misma carpeta que main.py"}

if __name__ == "__main__":
    import uvicorn
    # Cambiamos a puerto 8000
    uvicorn.run(app, host="127.0.0.1", port=8000)