from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Union
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class Ingredient(BaseModel):
    name: str
    stock: float
    unit: str
    type: str

class RecipeItem(BaseModel):
    name: str
    amount: float

class Plate(BaseModel):
    name: str
    price: float
    category: str = "Comida"
    recipe: List[RecipeItem]

class Table(BaseModel):
    id: int
    number: int
    capacity: int
    status: str = "Libre"
    order: List[dict] = []

db = {"ingredients": [], "plates": [], "tables": []}

@app.get("/")
def home(): return FileResponse("index.html")

# --- ALMACÉN ---
@app.get("/ingredients")
def get_ingredients(): return db["ingredients"]

@app.post("/ingredients")
def add_ingredient(item: Ingredient):
    db["ingredients"].append(item.dict())
    return item

# --- CARTA (Solo Comida) ---
@app.get("/plates")
def get_plates(): return db["plates"]

@app.post("/plates")
def create_plate(plate: Plate):
    db["plates"].append(plate.dict())
    return plate

# --- MESAS ---
@app.get("/tables")
def get_tables(): return db["tables"]

@app.post("/tables")
def create_table(table: Table):
    db["tables"].append(table.dict())
    return table

@app.put("/tables/{t_id}/status")
def update_status(t_id: int, status: str):
    for t in db["tables"]:
        if t["id"] == t_id:
            t["status"] = status
            if status == "Libre": t["order"] = []
            return t
    raise HTTPException(404)

@app.post("/tables/{t_id}/order")
def save_order(t_id: int, items: List[dict]):
    for t in db["tables"]:
        if t["id"] == t_id:
            t["order"] = items
            return {"ok": True}
    raise HTTPException(404)

@app.post("/tables/{t_id}/checkout")
def checkout(t_id: int):
    table = next((t for t in db["tables"] if t["id"] == t_id), None)
    for item in table["order"]:
        if "recipe" in item: # Es un plato elaborado
            for req in item["recipe"]:
                for ing in db["ingredients"]:
                    if ing["name"] == req["name"]:
                        ing["stock"] -= req["amount"]
        else: # Es una bebida directa del almacén
            for ing in db["ingredients"]:
                if ing["name"] == item["name"]:
                    ing["stock"] -= 1 # Se descuenta una unidad (botella/lata)
    table["status"] = "Libre"
    table["order"] = []
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)