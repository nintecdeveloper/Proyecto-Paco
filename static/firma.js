// Firma Digital - Obligatoria para cerrar partes de trabajo
class SignaturePad {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) {
            console.error('Canvas no encontrado:', canvasId);
            return;
        }
        
        this.ctx = this.canvas.getContext('2d');
        this.isDrawing = false;
        this.hasSignature = false;
        
        this.initCanvas();
        this.bindEvents();
    }
    
    initCanvas() {
        // Configurar tamaño del canvas
        const rect = this.canvas.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
        
        // Estilo del lienzo
        this.ctx.strokeStyle = '#f37021';
        this.ctx.lineWidth = 2;
        this.ctx.lineCap = 'round';
        this.ctx.lineJoin = 'round';
        
        // Fondo blanco
        this.ctx.fillStyle = '#ffffff';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    }
    
    bindEvents() {
        // Mouse events
        this.canvas.addEventListener('mousedown', (e) => this.startDrawing(e));
        this.canvas.addEventListener('mousemove', (e) => this.draw(e));
        this.canvas.addEventListener('mouseup', () => this.stopDrawing());
        this.canvas.addEventListener('mouseout', () => this.stopDrawing());
        
        // Touch events para móviles
        this.canvas.addEventListener('touchstart', (e) => {
            e.preventDefault();
            this.startDrawing(e.touches[0]);
        });
        this.canvas.addEventListener('touchmove', (e) => {
            e.preventDefault();
            this.draw(e.touches[0]);
        });
        this.canvas.addEventListener('touchend', (e) => {
            e.preventDefault();
            this.stopDrawing();
        });
    }
    
    getPosition(e) {
        const rect = this.canvas.getBoundingClientRect();
        return {
            x: (e.clientX || e.pageX) - rect.left,
            y: (e.clientY || e.pageY) - rect.top
        };
    }
    
    startDrawing(e) {
        this.isDrawing = true;
        const pos = this.getPosition(e);
        this.ctx.beginPath();
        this.ctx.moveTo(pos.x, pos.y);
        this.hasSignature = true;
    }
    
    draw(e) {
        if (!this.isDrawing) return;
        
        const pos = this.getPosition(e);
        this.ctx.lineTo(pos.x, pos.y);
        this.ctx.stroke();
    }
    
    stopDrawing() {
        if (this.isDrawing) {
            this.isDrawing = false;
            this.ctx.closePath();
        }
    }
    
    clear() {
        this.ctx.fillStyle = '#ffffff';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        this.hasSignature = false;
    }
    
    isEmpty() {
        return !this.hasSignature;
    }
    
    getDataURL() {
        return this.canvas.toDataURL('image/png');
    }
    
    fromDataURL(dataURL) {
        const img = new Image();
        img.onload = () => {
            this.ctx.drawImage(img, 0, 0);
            this.hasSignature = true;
        };
        img.src = dataURL;
    }
}

// Función para validar y completar un parte de trabajo
function completeTaskWithSignature(taskId, signaturePad) {
    // Verificar que hay firma
    if (signaturePad.isEmpty()) {
        alert('⚠️ La firma del cliente es OBLIGATORIA para cerrar el parte de trabajo.');
        return false;
    }
    
    // Obtener datos del formulario
    const formData = {
        signature: signaturePad.getDataURL(),
        parts: document.getElementById('partsInput')?.value || '',
        description: document.getElementById('descriptionInput')?.value || '',
        stock_item_id: document.getElementById('stockItemSelect')?.value || null,
        stock_quantity: document.getElementById('stockQuantity')?.value || 0,
        stock_action: document.getElementById('stockAction')?.value || 'used'
    };
    
    // Enviar al servidor
    fetch(`/complete_task/${taskId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('✅ Parte de trabajo completado correctamente');
            window.location.reload();
        } else {
            alert('❌ Error: ' + data.msg);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error al completar el parte de trabajo');
    });
}

// Exportar para uso global
window.SignaturePad = SignaturePad;
window.completeTaskWithSignature = completeTaskWithSignature;
