# 1. Traemos una imagen oficial y ligera (slim) de Python 3.12
FROM python:3.12-slim

# 2. Definimos /app como nuestra carpeta de trabajo dentro del contenedor
WORKDIR /app

# 3. Copiamos el requirements.txt que generaste en el paso 3
COPY requirements.txt .

# 4. Instalamos tus librerías (pandas, pyarrow, jupyter, etc.) sin guardar caché de instalación
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiamos todo el resto de tu código a la carpeta /app del contenedor
COPY . .

# 6. Habilitamos el puerto 8888 para que tu computadora pueda comunicarse con Jupyter
EXPOSE 8888

# 7. Instrucción final: al encender el contenedor, arranca Jupyter Lab
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]