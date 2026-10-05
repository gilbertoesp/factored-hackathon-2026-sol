# 1. Traemos una imagen oficial y ligera (slim) de Python 3.12
FROM python:3.12-slim

# 2. Definimos /app como nuestra carpeta de trabajo dentro del contenedor
WORKDIR /app

# 3. Copiamos el requirements.txt (versiones fijas)
COPY requirements.txt .

# 4. Instalamos las librerías sin guardar caché de instalación
# RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
RUN pip install -r requirements.txt

# 5. Copiamos el código (los datos y el .venv quedan fuera por .dockerignore)
COPY . .

# 6. Instrucción final: corre el ETL y termina (los datos crudos se montan en /data)
ENV ETL_INPUT_DIR=/data
CMD ["python", "etl_bank.py"]
