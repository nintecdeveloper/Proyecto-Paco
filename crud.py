from sqlalchemy.orm import Session
from fastapi import HTTPException
from datetime import datetime
import models
import schemas

# ==========================================
# --- MÓDULO INVENTARIO (EXISTENTE) ---
# ==========================================

def get_ingredients(db: Session):
    return db.query(models.Ingredient).all()

def create_ingredient(db: Session, ingredient: schemas.IngredientCreate):
    data = ingredient.model_dump() if hasattr(ingredient, 'model_dump') else ingredient.dict()
    new_ingredient = models.Ingredient(**data)
    db.add(new_ingredient)
    db.commit()
    db.refresh(new_ingredient)
    return new_ingredient

def create_purchase(db: Session, purchase_data: schemas.PurchaseCreate):
    new_purchase = models.Purchase(**purchase_data.dict())
    db.add(new_purchase)
    ingredient = db.query(models.Ingredient).filter(models.Ingredient.id == purchase_data.ingredient_id).first()
    if ingredient:
        ingredient.stock += purchase_data.quantity
    db.commit()
    db.refresh(new_purchase)
    return new_purchase

# ==========================================
# --- MÓDULO PLATOS Y ESCANDALLOS ---
# ==========================================

def create_dish(db: Session, dish_data: schemas.DishCreate):
    new_dish = models.Dish(name=dish_data.name, price=dish_data.price)
    db.add(new_dish)
    db.commit()
    db.refresh(new_dish)
    
    for item in dish_data.recipe_items:
        recipe_item = models.RecipeItem(
            dish_id=new_dish.id,
            ingredient_id=item.ingredient_id,
            quantity=item.quantity
        )
        db.add(recipe_item)
    db.commit()
    return new_dish

# ==========================================
# --- MÓDULO MESAS Y PEDIDOS (NUEVO) ---
# ==========================================

def get_tables(db: Session):
    return db.query(models.Table).all()

def create_table(db: Session, table: schemas.TableCreate):
    new_table = models.Table(**table.dict())
    db.add(new_table)
    db.commit()
    db.refresh(new_table)
    return new_table

def open_order(db: Session, order_data: schemas.OrderCreate):
    # 1. Cambiar estado de la mesa
    table = db.query(models.Table).filter(models.Table.id == order_data.table_id).first()
    if not table or table.status != "Libre":
        raise HTTPException(status_code=400, detail="Mesa no disponible")
    
    table.status = "Ocupada"
    
    # 2. Crear el pedido
    new_order = models.Order(
        table_id=order_data.table_id,
        opened_at=datetime.now(),
        is_paid=False
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    
    # 3. Añadir platos al pedido
    total = 0
    for item in order_data.items:
        order_item = models.OrderItem(
            order_id=new_order.id,
            dish_id=item.dish_id,
            quantity=item.quantity
        )
        db.add(order_item)
        # Sumar al precio total
        dish = db.query(models.Dish).filter(models.Dish.id == item.dish_id).first()
        if dish:
            total += (dish.price * item.quantity)
    
    new_order.total_price = total
    db.commit()
    return new_order

def close_order(db: Session, order_id: int):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order or order.is_paid:
        return None

    # 1. Marcar pedido como pagado y cerrar hora (HISTORIAL)
    order.is_paid = True
    order.closed_at = datetime.now()
    
    # 2. Liberar la mesa
    table = db.query(models.Table).filter(models.Table.id == order.table_id).first()
    table.status = "Libre"
    
    # 3. DESCUENTO AUTOMÁTICO DE STOCK (Escandallos)
    for item in order.items:
        dish = db.query(models.Dish).filter(models.Dish.id == item.dish_id).first()
        if dish:
            for r_item in dish.recipe_items:
                ingredient = db.query(models.Ingredient).filter(models.Ingredient.id == r_item.ingredient_id).first()
                if ingredient:
                    ingredient.stock -= (r_item.quantity * item.quantity)
    
    db.commit()
    return order

# ==========================================
# --- MÓDULO FACTURACIÓN (OCR) ---
# ==========================================

def create_invoice(db: Session, invoice_data: schemas.InvoiceCreate):
    new_invoice = models.Invoice(
        raw_text_ocr=invoice_data.raw_text_ocr,
        total_amount=invoice_data.total_amount,
        supplier_id=invoice_data.supplier_id,
        date=datetime.now()
    )
    db.add(new_invoice)
    db.commit()
    db.refresh(new_invoice)
    return new_invoice

# ==========================================
# --- MÓDULO SAT (EXISTENTE) ---
# ==========================================

def get_work_orders(db: Session):
    return db.query(models.WorkOrder).all()

def create_technician(db: Session, tech: schemas.TechnicianCreate):
    new_tech = models.Technician(**tech.dict())
    db.add(new_tech)
    db.commit()
    db.refresh(new_tech)
    return new_tech