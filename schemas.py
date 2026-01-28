from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# ==========================================
# --- MÓDULO HOSTALERÍA (EXISTENTE) ---
# ==========================================

class IngredientBase(BaseModel):
    name: str
    unit: str
    stock: float
    min_stock: float
    cost_per_unit: float
    supplier_id: Optional[int] = None

class IngredientCreate(IngredientBase): 
    pass

class IngredientResponse(IngredientBase):
    id: int
    class Config: 
        from_attributes = True

class RecipeItemCreate(BaseModel):
    ingredient_id: int
    quantity: float

class DishCreate(BaseModel):
    name: str
    price: float
    recipe_items: List[RecipeItemCreate]

class DishResponse(BaseModel):
    id: int
    name: str
    price: float
    class Config: 
        from_attributes = True

class PurchaseCreate(BaseModel):
    ingredient_id: int
    quantity: float
    cost_at_purchase: float
    date: str

# ==========================================
# --- MÓDULO RESTAURANTE (NUEVO: MESAS) ---
# ==========================================

class TableBase(BaseModel):
    number: int
    capacity: int
    status: str = "Libre"

class TableCreate(TableBase):
    pass

class TableResponse(TableBase):
    id: int
    class Config:
        from_attributes = True

# ==========================================
# --- MÓDULO PEDIDOS E HISTORIAL (NUEVO) ---
# ==========================================

class OrderItemBase(BaseModel):
    dish_id: int
    quantity: int

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemResponse(OrderItemBase):
    id: int
    class Config:
        from_attributes = True

class OrderCreate(BaseModel):
    table_id: int
    items: List[OrderItemCreate]

class OrderResponse(BaseModel):
    id: int
    table_id: int
    opened_at: datetime
    closed_at: Optional[datetime] = None
    is_paid: bool
    total_price: float
    items: List[OrderItemResponse]
    class Config:
        from_attributes = True

# ==========================================
# --- MÓDULO FACTURACIÓN OCR (NUEVO) ---
# ==========================================

class InvoiceCreate(BaseModel):
    raw_text_ocr: str
    total_amount: float
    supplier_id: int

class InvoiceResponse(BaseModel):
    id: int
    date: datetime
    raw_text_ocr: str
    total_amount: float
    supplier_id: int
    class Config:
        from_attributes = True

# ==========================================
# --- MÓDULO SAT (EXISTENTE) ---
# ==========================================

class WorkOrderBase(BaseModel):
    client_name: str
    description: str
    date: str
    status: str = "Pendiente"
    technician_id: int

class WorkOrderCreate(WorkOrderBase): 
    pass

class WorkOrderUpdate(BaseModel):
    summary: str
    time_spent: float
    status: str

class WorkOrderResponse(WorkOrderBase):
    id: int
    summary: Optional[str] = None
    time_spent: Optional[float] = None
    class Config: 
        from_attributes = True

class TechnicianCreate(BaseModel):
    name: str
    specialty: str

class TechnicianResponse(BaseModel):
    id: int
    name: str
    specialty: str
    class Config: 
        from_attributes = True