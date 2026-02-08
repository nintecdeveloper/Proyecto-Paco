import os
import json
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import io

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'oslaprint_pro_2026_secure_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'oslaprint.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20)) # 'admin' o 'tech'

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class ServiceType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), default='#6c757d') # Hex code color

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    quantity = db.Column(db.Integer, default=0)
    category = db.Column(db.String(50)) 

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tech_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    client_name = db.Column(db.String(100))
    description = db.Column(db.Text)
    
    date = db.Column(db.Date, default=date.today)
    start_time = db.Column(db.String(10)) 
    end_time = db.Column(db.String(10))   
    
    service_type = db.Column(db.String(50)) 
    parts_text = db.Column(db.String(200))  
    
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock.id'), nullable=True)
    stock_quantity_used = db.Column(db.Integer, default=0)
    stock_action = db.Column(db.String(20))

    status = db.Column(db.String(20), default='Completado')

    tech = db.relationship('User', backref='tasks')
    stock_item = db.relationship('Stock', backref='tasks')

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

# --- CONTEXT PROCESSOR ---
# Esto hace que 'all_service_types' esté disponible en TODOS los templates HTML automáticamente
@app.context_processor
def inject_globals():
    return dict(all_service_types=ServiceType.query.all())

# --- RUTAS PRINCIPALES ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Credenciales incorrectas.', 'danger')
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        empleados = User.query.filter_by(role='tech').all()
        informes = Task.query.filter_by(status='Completado').order_by(Task.date.desc()).all()
        inventory = Stock.query.order_by(Stock.name).all()
        clients = Client.query.order_by(Client.name).all()
        services = ServiceType.query.order_by(ServiceType.name).all()
        return render_template('admin_panel.html', empleados=empleados, informes=informes, inventory=inventory, clients=clients, services=services)
    
    stock_items = Stock.query.all()
    pending_tasks = Task.query.filter_by(tech_id=current_user.id, status='Pendiente').order_by(Task.date).all()
    
    # Nota: tech_panel.html también tendrá acceso a 'all_service_types' gracias al context_processor
    return render_template('tech_panel.html', 
                           today_date=date.today().strftime('%Y-%m-%d'), 
                           stock_items=stock_items,
                           pending_tasks=pending_tasks)

@app.route('/manage_services', methods=['POST'])
@login_required
def manage_services():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        existing = ServiceType.query.filter_by(name=request.form['name']).first()
        if not existing:
            db.session.add(ServiceType(name=request.form['name'], color=request.form['color']))
            flash('Tipo de servicio añadido.', 'success')
        else:
            flash('Ese servicio ya existe.', 'warning')
            
    elif action == 'edit':
        svc = ServiceType.query.get(request.form['service_id'])
        if svc:
            svc.name = request.form['name']
            svc.color = request.form['color']
            flash('Servicio actualizado.', 'success')
            
    elif action == 'delete':
        svc = ServiceType.query.get(request.form['service_id'])
        if svc:
            # Opcional: Podrías querer migrar las tareas viejas a otro tipo, 
            # pero por ahora simplemente las dejamos con el nombre antiguo (texto)
            db.session.delete(svc)
            flash('Tipo de servicio eliminado.', 'warning')
            
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/save_report', methods=['POST'])
@login_required
def save_report():
    try:
        nueva_fecha = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        stock_id = request.form.get('stock_item')
        qty = int(request.form.get('stock_qty', 0))
        action = request.form.get('stock_action', 'used')
        linked_task_id = request.form.get('linked_task_id')

        if stock_id and qty > 0:
            item = Stock.query.get(stock_id)
            if item:
                if action == 'used':
                    if item.quantity >= qty:
                        item.quantity -= qty
                    else:
                        flash(f'Error: Stock insuficiente de {item.name}', 'danger')
                        return redirect(url_for('dashboard'))
                elif action == 'retrieved':
                    item.quantity += qty
            
        if linked_task_id and linked_task_id != 'none':
            task = Task.query.get(linked_task_id)
            if task and task.tech_id == current_user.id:
                task.date = nueva_fecha
                task.start_time = request.form['entry_time']
                task.end_time = request.form['exit_time']
                nota_previa = task.description.replace("Cita Agendada: ", "")
                task.description = f"{request.form['description']} (Nota Cita: {nota_previa})"
                task.service_type = request.form['service_type']
                task.parts_text = request.form['parts_removed']
                task.stock_item_id = stock_id if (stock_id and qty > 0) else None
                task.stock_quantity_used = qty if (stock_id and qty > 0) else 0
                task.stock_action = action
                task.status = 'Completado'
                flash('Cita del calendario completada y parte generado.', 'success')
            else:
                flash('Error al vincular con la cita.', 'danger')
        else:
            new_task = Task(
                tech_id=current_user.id,
                client_name=request.form['client_name'],
                service_type=request.form['service_type'],
                date=nueva_fecha,
                start_time=request.form['entry_time'],
                end_time=request.form['exit_time'],
                description=request.form['description'],
                parts_text=request.form['parts_removed'], 
                stock_item_id=stock_id if (stock_id and qty > 0) else None,
                stock_quantity_used=qty if (stock_id and qty > 0) else 0,
                stock_action=action,
                status='Completado'
            )
            db.session.add(new_task)
            flash('Parte nuevo guardado correctamente.', 'success')

        db.session.commit()
        
    except Exception as e:
        flash(f'Error al guardar: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard'))

@app.route('/schedule_appointment', methods=['POST'])
@login_required
def schedule_appointment():
    try:
        target_tech_id = current_user.id
        if current_user.role == 'admin' and request.form.get('tech_id'):
            target_tech_id = int(request.form.get('tech_id'))

        nueva_fecha = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        hora = request.form.get('time', '')
        
        new_appt = Task(
            tech_id=target_tech_id,
            client_name=request.form['client_name'],
            service_type=request.form['service_type'],
            date=nueva_fecha,
            start_time=hora,
            description="Cita Agendada: " + request.form.get('notes', ''),
            status='Pendiente'
        )
        db.session.add(new_appt)
        db.session.commit()
        flash('Cita agendada correctamente.', 'info')
    except Exception as e:
        flash(f'Error al agendar: {str(e)}', 'danger')
    return redirect(url_for('dashboard'))

@app.route('/edit_appointment/<int:task_id>', methods=['POST'])
@login_required
def edit_appointment(task_id):
    try:
        task = Task.query.get_or_404(task_id)
        
        if current_user.role != 'admin' and task.tech_id != current_user.id:
            return jsonify({'success': False, 'msg': 'No autorizado'}), 403
        
        task.client_name = request.form.get('client_name')
        task.service_type = request.form.get('service_type')
        task.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        task.start_time = request.form.get('time', '')
        
        notes = request.form.get('notes', '')
        if notes:
            if "Cita Agendada:" in task.description:
                task.description = "Cita Agendada: " + notes
            else:
                task.description = notes
        
        db.session.commit()
        flash('Cita modificada correctamente.', 'success')
        
    except Exception as e:
        flash(f'Error al modificar: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/api/task_action/<int:task_id>/<action>', methods=['POST'])
@login_required
def task_action(task_id, action):
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and task.tech_id != current_user.id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403

    if action == 'delete':
        db.session.delete(task)
        msg = 'Tarea eliminada del calendario.'
    elif action == 'complete':
        task.status = 'Completado'
        if not task.start_time: task.start_time = "09:00"
        if not task.end_time: task.end_time = "10:00"
        msg = 'Tarea marcada como completada.'
    else:
        return jsonify({'success': False, 'msg': 'Acción inválida'}), 400

    db.session.commit()
    return jsonify({'success': True, 'msg': msg})

@app.route('/api/get_task/<int:task_id>')
@login_required
def get_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and task.tech_id != current_user.id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    notes = task.description
    if "Cita Agendada: " in notes:
        notes = notes.replace("Cita Agendada: ", "")
    
    return jsonify({
        'success': True,
        'data': {
            'id': task.id,
            'client_name': task.client_name,
            'service_type': task.service_type,
            'date': task.date.strftime('%Y-%m-%d'),
            'time': task.start_time or '',
            'notes': notes,
            'status': task.status
        }
    })

@app.route('/manage_stock', methods=['POST'])
@login_required
def manage_stock():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    
    action = request.form['action']
    
    if action == 'add':
        db.session.add(Stock(name=request.form['name'], category=request.form['category'], quantity=int(request.form['quantity'])))
        flash('Artículo añadido.', 'success')
    elif action == 'update':
        item = Stock.query.get(request.form['item_id'])
        if item:
            item.quantity += int(request.form['quantity'])
            if item.quantity < 0: item.quantity = 0
            flash(f'Stock ajustado: {item.name}', 'success')
    elif action == 'edit_full':
        item = Stock.query.get(request.form['item_id'])
        if item:
            item.name = request.form['name']
            item.category = request.form['category']
            item.quantity = int(request.form['quantity'])
            flash(f'Artículo editado: {item.name}', 'success')
    elif action == 'delete':
        Stock.query.filter_by(id=request.form['item_id']).delete()
        flash('Artículo eliminado.', 'warning')

    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/manage_clients', methods=['POST'])
@login_required
def manage_clients():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        existing = Client.query.filter_by(name=request.form['name']).first()
        if not existing:
            db.session.add(Client(name=request.form['name']))
            flash('Cliente añadido a la base de datos.', 'success')
        else:
            flash('Este cliente ya existe.', 'warning')
            
    elif action == 'edit':
        client = Client.query.get(request.form['client_id'])
        if client:
            client.name = request.form['name']
            flash('Nombre de cliente actualizado.', 'success')
            
    elif action == 'delete':
        Client.query.filter_by(id=request.form['client_id']).delete()
        flash('Cliente eliminado.', 'warning')
        
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/export_clients')
@login_required
def export_clients():
    if current_user.role != 'admin':
        flash('No autorizado', 'danger')
        return redirect(url_for('dashboard'))
    
    clients = Client.query.all()
    clients_data = [{'id': c.id, 'name': c.name} for c in clients]
    
    json_data = json.dumps(clients_data, ensure_ascii=False, indent=2)
    
    mem_file = io.BytesIO()
    mem_file.write(json_data.encode('utf-8'))
    mem_file.seek(0)
    
    return send_file(
        mem_file,
        mimetype='application/json',
        as_attachment=True,
        download_name=f'clientes_oslaprint_{date.today().strftime("%Y%m%d")}.json'
    )

@app.route('/import_clients', methods=['POST'])
@login_required
def import_clients():
    if current_user.role != 'admin':
        flash('No autorizado', 'danger')
        return redirect(url_for('dashboard'))
    
    if 'file' not in request.files:
        flash('No se seleccionó ningún archivo', 'danger')
        return redirect(url_for('dashboard'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No se seleccionó ningún archivo', 'danger')
        return redirect(url_for('dashboard'))
    
    if not file.filename.endswith('.json'):
        flash('El archivo debe ser formato JSON', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        content = file.read().decode('utf-8')
        clients_data = json.loads(content)
        
        added = 0
        skipped = 0
        
        for client_info in clients_data:
            name = client_info.get('name', '').strip()
            if name:
                existing = Client.query.filter_by(name=name).first()
                if not existing:
                    db.session.add(Client(name=name))
                    added += 1
                else:
                    skipped += 1
        
        db.session.commit()
        flash(f'Importación completada: {added} clientes añadidos, {skipped} ya existían', 'success')
        
    except json.JSONDecodeError:
        flash('Error: El archivo JSON no es válido', 'danger')
    except Exception as e:
        flash(f'Error al importar: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/api/clients_search')
@login_required
def search_clients():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    results = Client.query.filter(Client.name.ilike(f'%{query}%')).order_by(Client.name).limit(10).all()
    return jsonify([{'name': c.name} for c in results])

@app.route('/print_report/<int:task_id>')
@login_required
def print_report(task_id):
    task = Task.query.get_or_404(task_id)
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return "Acceso denegado", 403
        
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <title>Parte #{task.id}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ font-family: Arial, sans-serif; padding: 40px; max-width: 800px; margin: auto; }}
            .header {{ border-bottom: 3px solid #f37021; padding-bottom: 20px; margin-bottom: 30px; }}
            .logo {{ font-size: 24px; font-weight: bold; }}
            .label {{ font-weight: bold; color: #666; font-size: 0.9em; }}
            .value {{ font-size: 1.1em; margin-bottom: 15px; }}
            .box {{ background: #f9f9f9; padding: 15px; border-radius: 5px; border: 1px solid #ddd; }}
        </style>
    </head>
    <body onload="window.print()">
        <div class="header d-flex justify-content-between align-items-center">
            <div class="logo">OSLA<span style="color:#f37021">PRINT</span></div>
            <div class="text-end">
                <h4>PARTE DE TRABAJO</h4>
                <small>Ref: #{task.id} | Fecha: {task.date.strftime('%d/%m/%Y')}</small>
            </div>
        </div>
        
        <div class="row">
            <div class="col-6">
                <div class="label">CLIENTE</div>
                <div class="value">{task.client_name}</div>
            </div>
            <div class="col-6">
                <div class="label">TÉCNICO</div>
                <div class="value">{task.tech.username.upper()}</div>
            </div>
        </div>
        
        <div class="row mt-3">
            <div class="col-4">
                <div class="label">SERVICIO</div>
                <div class="value">{task.service_type}</div>
            </div>
            <div class="col-4">
                <div class="label">HORA ENTRADA</div>
                <div class="value">{task.start_time}</div>
            </div>
            <div class="col-4">
                <div class="label">HORA SALIDA</div>
                <div class="value">{task.end_time}</div>
            </div>
        </div>
        
        <div class="mt-4">
            <div class="label">DESCRIPCIÓN DEL TRABAJO</div>
            <div class="box">{task.description}</div>
        </div>
        
        <div class="row mt-4">
            <div class="col-6">
                <div class="label">MATERIAL UTILIZADO/RETIRADO</div>
                <div class="box">
                    { f"Stock ({'USADO' if task.stock_action == 'used' else 'RETIRADO'}): {task.stock_quantity_used}x {task.stock_item.name}<br>" if task.stock_item else "" }
                    { f"Notas/Retirado: {task.parts_text}" if task.parts_text else "Sin notas adicionales" }
                </div>
            </div>
        </div>
        
        <div class="mt-5 text-center text-muted small">
            <p>Documento generado electrónicamente por OSLAPRINT SYSTEM</p>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/api/tasks')
@login_required
def my_tasks():
    tasks = Task.query.filter_by(tech_id=current_user.id).all()
    return format_events(tasks)

@app.route('/api/admin/tasks/<int:user_id>')
@login_required
def get_admin_tasks(user_id):
    tasks = Task.query.filter_by(tech_id=user_id).all()
    return format_events(tasks)

@app.route('/api/admin/all_tasks')
@login_required
def get_all_admin_tasks():
    if current_user.role != 'admin':
        return jsonify([])
    tasks = Task.query.all()
    return format_events(tasks)

def format_events(tasks):
    # Cargar tipos de la BD y mapear nombre -> color
    all_types = ServiceType.query.all()
    type_colors = {s.name: s.color for s in all_types}
    
    events = []
    for t in tasks:
        # Asignar color según el tipo en BD, por defecto Gris (#6c757d)
        color = type_colors.get(t.service_type, '#6c757d')
        
        title = f"{t.client_name} ({t.service_type})"
        
        events.append({
            'id': t.id,
            'title': title,
            'start': f"{t.date}T{t.start_time}" if t.start_time else str(t.date),
            'color': color,
            'allDay': False if t.start_time else True,
            'extendedProps': {
                'status': t.status,
                'client': t.client_name,
                'desc': t.description,
                'tech_name': t.tech.username.upper(),
                'service_type': t.service_type
            }
        })
    return jsonify(events)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

def init_db():
    with app.app_context():
        db.create_all()
        
        # Usuarios Base
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', role='admin', password_hash=generate_password_hash('admin123')))
        if not User.query.filter_by(username='tech').first():
            db.session.add(User(username='tech', role='tech', password_hash=generate_password_hash('tech123')))
        if not User.query.filter_by(username='carlos').first():
            db.session.add(User(username='carlos', role='tech', password_hash=generate_password_hash('carlos123')))
        if not User.query.filter_by(username='maria').first():
            db.session.add(User(username='maria', role='tech', password_hash=generate_password_hash('maria123')))
        
        # Tipos de Servicio por Defecto (Carga inicial)
        if not ServiceType.query.first():
            initial_services = [
                {'name': 'Revisión', 'color': '#0d6efd'},
                {'name': 'Instalación', 'color': '#6f42c1'},
                {'name': 'Urgencia', 'color': '#dc3545'},
                {'name': 'Avería', 'color': '#fd7e14'},
                {'name': 'Mantenimiento', 'color': '#20c997'},
                {'name': 'Otro', 'color': '#adb5bd'}
            ]
            for s in initial_services:
                db.session.add(ServiceType(name=s['name'], color=s['color']))

        # Stock Base
        if not Stock.query.first():
            db.session.add(Stock(name='Toner Genérico', category='Consumible', quantity=10))
            db.session.add(Stock(name='Fusor HP 4000', category='Pieza', quantity=2))
        
        # Clientes Base
        if not Client.query.first():
            sample_clients = [
                'Oficinas Centrales Bankia', 'Talleres Manolo S.L.', 'Colegio San José', 
                'Hospital General', 'Gestoría López', 'Restaurante El Puerto', 
                'Inmobiliaria Sol', 'Centro Deportivo Municipal', 'Librería Cervantes'
            ]
            for c in sample_clients:
                db.session.add(Client(name=c))
                
        db.session.commit()

# --- BLOQUE DE INICIALIZACIÓN UNIFICADO ---
with app.app_context():
    # Primero creamos las tablas (la estructura)
    db.create_all()
    
    # Después llenamos los datos (el contenido)
    # 1. Usuarios
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', role='admin', password_hash=generate_password_hash('admin123')))
        db.session.add(User(username='tech', role='tech', password_hash=generate_password_hash('tech123')))
    
    # 2. Tipos de Servicio y Colores (Lo que hacía fallar el admin)
    if not ServiceType.query.first():
        servicios = [
            {'name': 'Revisión', 'color': '#0d6efd'},
            {'name': 'Instalación', 'color': '#6f42c1'},
            {'name': 'Urgencia', 'color': '#dc3545'},
            {'name': 'Avería', 'color': '#fd7e14'},
            {'name': 'Mantenimiento', 'color': '#20c997'},
            {'name': 'Otro', 'color': '#adb5bd'}
        ]
        for s in servicios:
            db.session.add(ServiceType(name=s['name'], color=s['color']))

    # 3. Datos de ejemplo
    if not Stock.query.first():
        db.session.add(Stock(name='Toner Genérico', category='Consumible', quantity=10))
    if not Client.query.first():
        db.session.add(Client(name='Cliente Ejemplo'))
        
    db.session.commit()

# --- ARRANQUE ---
if __name__ == '__main__':
    app.run(debug=True)