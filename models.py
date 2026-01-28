from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

# --- MÓDULO BASE Y PROVEEDORES ---
class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    contact = Column(String)
    ingredients = relationship("Ingredient", back_populates="supplier")
    invoices = relationship("Invoice", back_populates="supplier")

# --- MÓDULO INVENTARIO ---
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

class Purchase(Base):
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"))
    quantity = Column(Float)
    cost_at_purchase = Column(Float)
    date = Column(String)

# --- MÓDULO CARTA Y RECETAS ---
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

# --- MÓDULO RESTAURANTE (MESAS Y PEDIDOS) ---
class Table(Base):
    __tablename__ = "tables"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, unique=True, nullable=False)
    capacity = Column(Integer)
    status = Column(String, default="Libre") # Libre, Ocupada, Cuenta
    orders = relationship("Order", back_populates="table")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer, ForeignKey("tables.id"))
    opened_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime, nullable=True)
    is_paid = Column(Boolean, default=False)
    total_price = Column(Float, default=0.0)
    
    table = relationship("Table", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    dish_id = Column(Integer, ForeignKey("dishes.id"))
    quantity = Column(Integer)
    
    order = relationship("Order", back_populates="items")
    dish = relationship("Dish")

# --- MÓDULO FACTURACIÓN (OCR) ---
class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    raw_text_ocr = Column(String)
    total_amount = Column(Float)
    date = Column(DateTime, default=datetime.now)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    supplier = relationship("Supplier", back_populates="invoices")

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
    status = Column(String, default="Pendiente")
    date = Column(String)
    technician_id = Column(Integer, ForeignKey("technicians.id"))
    technician = relationship("Technician", back_populates="work_orders")