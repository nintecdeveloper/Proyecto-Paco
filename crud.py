from sqlalchemy.orm import Session
from fastapi import HTTPException
import models
import schemas

def get_ingredients(db: Session):
    return db.query(models.Ingredient).all()

def create_ingredient(db: Session, ingredient: schemas.IngredientCreate):
    try:
        # Compatibilidad con Pydantic v1 y v2
        data = ingredient.model_dump() if hasattr(ingredient, 'model_dump') else ingredient.dict()
        
        new_ingredient = models.Ingredient(**data)
        
        db.add(new_ingredient)
        db.commit()
        db.refresh(new_ingredient)
        
        print(f"Ingrediente creado con ID: {new_ingredient.id}")
        return new_ingredient
    except Exception as e:
        db.rollback()
        print(f"Error al crear ingrediente: {e}")
        raise e

def create_dish(db: Session, dish_data: schemas.DishCreate):
    try:
        # 1. Crear el plato
        new_dish = models.Dish(name=dish_data.name, price=dish_data.price)
        db.add(new_dish)
        db.commit()
        db.refresh(new_dish)

        # 2. Crear la receta asociada a ese plato
        new_recipe = models.Recipe(dish_id=new_dish.id)
        db.add(new_recipe)
        db.commit()
        db.refresh(new_recipe)

        # 3. Añadir los ingredientes a la receta
        for item in dish_data.recipe_items:
            recipe_item = models.RecipeItem(
                recipe_id=new_recipe.id,
                ingredient_id=item.ingredient_id,
                quantity=item.quantity
            )
            db.add(recipe_item)
        
        db.commit()
        db.refresh(new_dish)
        return new_dish
    except Exception as e:
        db.rollback()
        print(f"Error al crear plato: {e}")
        raise e

def sell_dish(db: Session, dish_id: int, quantity: int = 1):
    dish = db.query(models.Dish).filter(models.Dish.id == dish_id).first()

    if not dish or not dish.recipe:
        raise HTTPException(status_code=404, detail="Plato no encontrado")

    # 1. Comprobar stock de todos los ingredientes antes de restar nada
    for item in dish.recipe.items:
        needed = item.quantity * quantity
        if item.ingredient.stock < needed:
            raise HTTPException(
                status_code=400, 
                detail=f"Stock insuficiente de {item.ingredient.name}"
            )

    # 2. Si hay stock de todo, procedemos a restar
    for item in dish.recipe.items:
        item.ingredient.stock -= item.quantity * quantity

    db.commit()

def get_low_stock_ingredients(db: Session):
    # Filtra ingredientes donde el stock actual es menor o igual al mínimo configurado
    return db.query(models.Ingredient).filter(models.Ingredient.stock <= models.Ingredient.min_stock).all()

def update_ingredient_stock(db: Session, ingredient_id: int, quantity: int):
    db_ingredient = db.query(models.Ingredient).filter(models.Ingredient.id == ingredient_id).first()
    if not db_ingredient:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado")
    
    # Sumamos la nueva cantidad al stock existente
    db_ingredient.stock += quantity
    
    db.commit()
    db.refresh(db_ingredient)
    return db_ingredient

def check_dishes_availability(db: Session):
    dishes = db.query(models.Dish).all()
    availability_list = []

    for dish in dishes:
        if not dish.recipe or not dish.recipe.items:
            availability_list.append({"dish_id": dish.id, "name": dish.name, "is_available": False, "possible_quantity": 0})
            continue

        can_cook = True
        limit_quantities = []

        for item in dish.recipe.items:
            if item.ingredient.stock < item.quantity:
                can_cook = False
                limit_quantities.append(0)
            else:
                # Calculamos cuántas veces podemos usar ese ingrediente
                possible = int(item.ingredient.stock / item.quantity)
                limit_quantities.append(possible)

        availability_list.append({
            "dish_id": dish.id,
            "name": dish.name,
            "is_available": can_cook,
            "possible_quantity": min(limit_quantities) if limit_quantities else 0
        })
    return availability_list

def create_supplier(db: Session, supplier: schemas.SupplierCreate):
    new_supplier = models.Supplier(name=supplier.name, contact=supplier.contact)
    db.add(new_supplier)
    db.commit()
    db.refresh(new_supplier)
    return new_supplier

def create_purchase(db: Session, purchase_data: schemas.PurchaseCreate):
    # 1. Registrar la compra en el historial
    new_purchase = models.Purchase(**purchase_data.dict())
    db.add(new_purchase)
    
    # 2. Actualizar el stock del ingrediente 
    ingredient = db.query(models.Ingredient).filter(models.Ingredient.id == purchase_data.ingredient_id).first()
    if ingredient:
        ingredient.stock += purchase_data.quantity
    
    db.commit()
    db.refresh(new_purchase)
    return new_purchase

def create_supplier(db: Session, name: str, contact: str):
    new_supplier = models.Supplier(name=name, contact=contact)
    db.add(new_supplier)
    db.commit()
    db.refresh(new_supplier)
    return new_supplier

def get_available_dishes(db: Session):
    dishes = db.query(models.Dish).all()
    available_list = []

    for dish in dishes:
        if not dish.recipe:
            continue
        
        is_possible = True
        # Comprobamos cada ingrediente del escandall 
        for item in dish.recipe.items:
            if item.ingredient.stock < item.quantity:
                is_possible = False
                break
        
        if is_possible:
            available_list.append(dish)
            
    return available_list