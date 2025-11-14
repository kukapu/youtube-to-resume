FROM python:3.11-slim

# Instalar dependencias del sistema necesarias para yt-dlp y ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Establecer directorio de trabajo
WORKDIR /app

# Copiar archivos de dependencias
COPY requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY main.py .
COPY database.py .
COPY index.html .

# Exponer puerto
EXPOSE 8000

# Variables de entorno por defecto
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

# Comando para ejecutar la aplicación
CMD ["python", "main.py"]
