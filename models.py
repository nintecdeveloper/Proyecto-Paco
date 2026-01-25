from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    contact = Column(String)
    ingredients = relationship("Ingredient", back_populates="supplier")

class Ingredient(Base):
    __tablename__ = "ingredients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    unit = Column(String)
    stock = Column(Float, default=0.0)
    min_stock = Column(Float, default=0.0)
    cost_per_unit = Column(Float, default=0.0)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    supplier = relationship("Supplier", back_populates="ingredients")
    recipe_items = relationship("RecipeItem", back_populates="ingredient")

class Dish(Base):
    __tablename__ = "dishes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    price = Column(Float)
    recipe_items = relationship("RecipeItem", back_populates="dish", cascade="all, delete-orphan")

class RecipeItem(Base):
    __tablename__ = "recipe_items"
    id = Column(Integer, primary_key=True, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"))
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"))
    quantity = Column(Float)
    dish = relationship("Dish", back_populates="recipe_items")
    ingredient = relationship("Ingredient", back_populates="recipe_items")

class Purchase(Base):
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"))
    quantity = Column(Float)
    cost_at_purchase = Column(Float)
    date = Column(String)

# --- MÓDULO SAT (TÉCNICOS) ---
class Technician(Base):
    __tablename__ = "technicians"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    specialty = Column(String)
    work_orders = relationship("WorkOrder", back_populates="technician")

class WorkOrder(Base):
    __tablename__ = "work_orders"
    id = Column(Integer, primary_key=True, index=True)
    client_name = Column(String, nullable=False)
    description = Column(String)
    status = Column(String, default="Pendiente") # Pendiente, Realizado
    date = Column(String)
    technician_id = Column(Integer, ForeignKey("technicians.id"))
    technician = relationship("Technician", back_populates="work_orders")