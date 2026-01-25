from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
import models, schemas, database

models.Base.metadata.create_all(bind=database.engine)
app = FastAPI(title="PACO ERP - Sistema Integral")

def get_db():
    db = database.SessionLocal()
    try: yield db
    finally: db.close()

# --- HOSTELERÍA ---
@app.get("/ingredients", response_model=List[schemas.IngredientResponse])
def list_ingredients(db: Session = Depends(get_db)):
    return db.query(models.Ingredient).all()

@app.post("/ingredients", response_model=schemas.IngredientResponse)
def create_ingredient(ingredient: schemas.IngredientCreate, db: Session = Depends(get_db)):
    db_item = models.Ingredient(**ingredient.dict())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.get("/dashboard/alerts")
def get_alerts(db: Session = Depends(get_db)):
    low_stock = db.query(models.Ingredient).filter(models.Ingredient.stock <= models.Ingredient.min_stock).all()
    total = db.query(models.Ingredient).count()
    return {"low_stock_count": len(low_stock), "total_ingredients": total}

# --- SAT (TÉCNICOS) ---
@app.get("/work-orders", response_model=List[schemas.WorkOrderResponse])
def get_orders(db: Session = Depends(get_db)):
    return db.query(models.WorkOrder).all()

@app.patch("/work-orders/{order_id}/complete")
def complete_work_order(order_id: int, update_data: schemas.WorkOrderUpdate, db: Session = Depends(get_db)):
    db_order = db.query(models.WorkOrder).filter(models.WorkOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    
    db_order.status = update_data.status
    db_order.summary = update_data.summary
    db_order.time_spent = update_data.time_spent
    db.commit()
    return {"message": "Parte guardado"}

# --- FRONTEND ---
app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/")
async def read_index():
    return FileResponse('static/index.html')