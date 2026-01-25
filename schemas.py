from pydantic import BaseModel
from typing import List, Optional

# --- MÓDULO HOSTALERÍA ---
class IngredientBase(BaseModel):
    name: str
    unit: str
    stock: float
    min_stock: float
    cost_per_unit: float
    supplier_id: Optional[int] = None

class IngredientCreate(IngredientBase): pass
class IngredientResponse(IngredientBase):
    id: int
    class Config: from_attributes = True

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
    class Config: from_attributes = True

# --- MÓDULO SAT ---
class WorkOrderBase(BaseModel):
    client_name: str
    description: str
    date: str
    status: str = "Pendiente"
    technician_id: int

class WorkOrderCreate(WorkOrderBase): pass

class WorkOrderUpdate(BaseModel):
    summary: str
    time_spent: float
    status: str

class WorkOrderResponse(WorkOrderBase):
    id: int
    summary: Optional[str] = None
    time_spent: Optional[float] = None
    class Config: from_attributes = True

class TechnicianBase(BaseModel):
    name: str
    specialty: str

class TechnicianCreate(TechnicianBase): pass

class TechnicianResponse(TechnicianBase):
    id: int
    class Config: from_attributes = True