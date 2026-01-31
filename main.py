import base64
import os
import json
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from openai import OpenAI

# --- CONFIGURACIÓN DE LA API KEY ---
# CORRECCIÓN: Pasamos la key directamente como string.
# NOTA DE SEGURIDAD: No compartas este archivo con la key puesta. 
# Para producción, usa un archivo .env
client = OpenAI(api_key="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")

app = FastAPI()

# Configuración de CORS para permitir que el HTML local hable con este servidor
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir el archivo HTML al entrar a la raíz
@app.get("/")
def home(): 
    # Asegúrate de que index.html esté en la misma carpeta que main.py
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"error": "Archivo index.html no encontrado"}

# --- ENDPOINT DE INTELIGENCIA ARTIFICIAL ---
@app.post("/api/scan-invoice")
async def scan_invoice(file: UploadFile = File(...)):
    try:
        print(f"Recibiendo archivo: {file.filename}")
        
        # 1. Leer la imagen y convertirla a base64
        contents = await file.read()
        base64_image = base64.b64encode(contents).decode('utf-8')

        # 2. Preparar el prompt para GPT-4o
        print("Enviando a OpenAI...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analiza esta factura de restaurante/proveedor. Extrae los items comprados. Devuelve SOLO un JSON válido (sin markdown, sin explicaciones) con este formato exacto: [{'name': 'nombre producto', 'qty': cantidad_numerica, 'price': costo_total_numerico, 'unit': 'unidad estimada (kg, litros, unidad)'}]. Si hay dudas, estima lo mejor posible."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            },
                        },
                    ],
                }
            ],
            max_tokens=1000,
        )

        # 3. Limpiar y parsear la respuesta
        content = response.choices[0].message.content
        print("Respuesta recibida de OpenAI")
        
        # Eliminar posibles bloques de código ```json ... ``` que a veces devuelve GPT
        content = content.replace("```json", "").replace("```", "").strip()
        
        data = json.loads(content)
        return JSONResponse(content={"status": "success", "data": data})

    except Exception as e:
        print(f"Error procesando factura: {str(e)}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    print("Iniciando servidor PACO ERP con IA...")
    print("Abre en tu navegador: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)