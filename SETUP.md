# Configuración de APIs de Transcripción

## Groq API (GRATIS - Recomendado)

### Obtener tu API Key:

1. Ve a https://console.groq.com/
2. Crea una cuenta (es gratis)
3. Ve a "API Keys" en el menú lateral
4. Crea una nueva API key
5. Copia la key (empieza con `gsk_...`)

### Configurar en el proyecto:

Edita el archivo `.env` y reemplaza:

```bash
GROQ_API_KEY=your_groq_api_key_here
```

Por:

```bash
GROQ_API_KEY=gsk_tu_key_aqui
```

## OpenAI API (Opcional - Backup)

Si quieres tener OpenAI como respaldo (de pago):

1. Ve a https://platform.openai.com/api-keys
2. Crea una API key
3. Agrega al `.env`:

```bash
OPENAI_API_KEY=sk-tu_key_aqui
```

## Límites y Costos

### Groq Whisper (Gratis)
- **Costo**: GRATIS
- **Límite**: 25MB por archivo
- **Velocidad**: Muy rápido (hasta 10x más rápido que OpenAI)
- **Modelo**: whisper-large-v3
- **Límite de requests**: Generoso para uso personal

### OpenAI Whisper (Backup)
- **Costo**: $0.006 por minuto (~$0.36/hora)
- **Límite**: 25MB por archivo
- **Velocidad**: Normal
- **Modelo**: whisper-1

## Cómo funciona la transcripción

1. **Primero**: Intenta obtener subtítulos (GRATIS)
2. **Si no hay subtítulos**: Descarga el audio a baja calidad (32kbps)
3. **Comprime si es necesario**: Para que quepa en 25MB
4. **Transcribe con Groq**: API gratuita
5. **Si Groq falla**: Usa OpenAI (si está configurada)

## Verificar configuración

Después de configurar la API key, reinicia el servidor y prueba con un video sin subtítulos.
Deberías ver mensajes como:

```
📁 Audio descargado: 2.45MB
🎤 Transcribiendo con Groq (gratis)...
✓ Transcripción completada con Groq (15234 caracteres)
```
