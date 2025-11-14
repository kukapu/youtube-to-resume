# 📺 YouTube Summarizer

Aplicación web que genera resúmenes en español de videos de YouTube de forma económica y eficiente.

## ✨ Características

- **💰 Económico**: Usa subtítulos cuando están disponibles (gratis). Si no hay subtítulos, transcribe el audio. Costo típico: $0.001-$0.03 por video.
- **🇪🇸 Resúmenes en Español**: Todos los resúmenes se generan en español, sin importar el idioma del video original.
- **⚡ Rápido**: Procesamiento inteligente con prioridad a subtítulos (instantáneo) y fallback a transcripción.
- **📥 Descargable**: Descarga los resúmenes en formato TXT para guardarlos.
- **🎯 Simple**: Interfaz web intuitiva - solo pega la URL y obtén tu resumen.

## 🏗️ Arquitectura

**Stack:**
- **Backend**: FastAPI (Python)
- **Extracción de texto**:
  1. Primera opción: `youtube-transcript-api` (subtítulos - GRATIS)
  2. Fallback: `yt-dlp` + Whisper vía OpenRouter (si no hay subtítulos)
- **Resumen**: OpenRouter con modelos económicos (GPT-4o-mini por defecto)
- **Frontend**: HTML/CSS/JS vanilla
- **Deploy**: Docker + Docker Compose

**Flujo de trabajo:**
```
URL de YouTube → Extraer ID → ¿Subtítulos disponibles?
                                      ↓
                          Sí ───────→ Usar subtítulos (GRATIS)
                          No ───────→ Descargar audio → Transcribir (Whisper)
                                      ↓
                              Generar resumen (OpenRouter)
                                      ↓
                              Mostrar resultado en español
```

## 🚀 Instalación Local

### Requisitos previos
- Python 3.11+
- FFmpeg (para extracción de audio)
- Cuenta en [OpenRouter](https://openrouter.ai/) con API key

### Pasos

1. **Clonar el repositorio**
```bash
git clone <tu-repo>
cd youtube-summarizer
```

2. **Crear archivo .env**
```bash
cp .env.example .env
```

3. **Configurar variables de entorno en .env**
```env
OPENROUTER_API_KEY=tu_api_key_aqui
SUMMARY_MODEL=openai/gpt-4o-mini
TRANSCRIPTION_MODEL=openai/whisper-large-v3
PORT=8000
```

4. **Instalar dependencias**
```bash
pip install -r requirements.txt
```

5. **Ejecutar la aplicación**
```bash
python main.py
```

6. **Abrir en el navegador**
```
http://localhost:8000
```

## 🐳 Instalación con Docker

### Desarrollo local

1. **Crear archivo .env** (igual que arriba)

2. **Construir y ejecutar**
```bash
docker-compose up --build
```

3. **Abrir en el navegador**
```
http://localhost:8000
```

### Despliegue en Dokploy (Hetzner)

1. **En tu VPS con Dokploy instalado:**

2. **Clonar el repositorio en el servidor**
```bash
git clone <tu-repo>
cd youtube-summarizer
```

3. **Crear archivo .env con tus credenciales**
```bash
nano .env
# Añade tu OPENROUTER_API_KEY y otras variables
```

4. **Desde Dokploy:**
   - Crear nueva aplicación
   - Tipo: Docker Compose
   - Ruta al proyecto: `/ruta/a/youtube-summarizer`
   - Variables de entorno: Configura `OPENROUTER_API_KEY`
   - Deploy!

5. **Configurar dominio** (opcional):
   - En Dokploy, configura un dominio o subdominio
   - Ejemplo: `youtube-summarizer.tudominio.com`

## 📖 Uso

### Interfaz Web

1. Abre la aplicación en tu navegador
2. Pega la URL de un video de YouTube
3. Haz clic en "Generar Resumen"
4. Espera mientras se procesa (10-60 segundos dependiendo del método)
5. Lee el resumen generado en español
6. (Opcional) Descarga el resumen en formato TXT

### API

También puedes usar la API directamente:

**Endpoint**: `POST /api/summarize`

**Request:**
```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "language": "es"
}
```

**Response:**
```json
{
  "video_id": "dQw4w9WgXcQ",
  "title": "Título del video",
  "transcript_method": "subtitles",
  "summary": "## Tema principal\n...",
  "cost_estimate": "~$0.001 - $0.002 (solo resumen)"
}
```

**Ejemplo con curl:**
```bash
curl -X POST http://localhost:8000/api/summarize \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=VIDEO_ID", "language": "es"}'
```

## 💰 Costos Estimados

Los costos dependen de si el video tiene subtítulos o no:

### Con subtítulos (mayoría de los casos)
- Extracción de subtítulos: **GRATIS**
- Resumen con GPT-4o-mini: **~$0.001 - $0.002**
- **Total: ~$0.001 - $0.002 por video**

### Sin subtítulos (menos común)
- Transcripción con Whisper Large v3: **~$0.006 - $0.02**
- Resumen con GPT-4o-mini: **~$0.001 - $0.002**
- **Total: ~$0.01 - $0.03 por video**

**Modelos alternativos aún más baratos:**
- `meta-llama/llama-3.1-8b-instruct`: ~5x más barato que GPT-4o-mini
- `anthropic/claude-3-haiku`: Buena calidad, precio medio

## 🔧 Configuración

### Cambiar modelo de resumen

Edita `.env`:
```env
# Opciones:
SUMMARY_MODEL=openai/gpt-4o-mini              # Recomendado (barato y bueno)
SUMMARY_MODEL=meta-llama/llama-3.1-8b-instruct # Más barato
SUMMARY_MODEL=anthropic/claude-3-haiku        # Alternativa
```

### Cambiar modelo de transcripción

Edita `.env`:
```env
TRANSCRIPTION_MODEL=openai/whisper-large-v3   # Recomendado
```

### Cambiar puerto

Edita `.env`:
```env
PORT=3000  # O el puerto que prefieras
```

## 📊 Características Técnicas

### Extracción de subtítulos
- Prioridad a subtítulos en español
- Fallback a inglés y otros idiomas
- Soporta subtítulos automáticos y manuales

### Transcripción de audio
- Descarga solo audio (no video completo) para ahorrar ancho de banda
- Usa calidad de audio baja (64kbps) para ahorrar en transcripción
- Limpia archivos temporales automáticamente

### Generación de resumen
- Limita el texto a 15,000 caracteres para controlar costos
- Formato estructurado: tema, puntos clave, conclusiones
- Salida en Markdown para fácil lectura

### Seguridad
- No guarda videos ni audios en el servidor
- No almacena transcripciones
- Solo procesa y devuelve el resumen

## 🛠️ Solución de Problemas

### Error: "No se pudo obtener el contenido del video"
- Verifica que la URL sea válida
- Algunos videos pueden tener restricciones de región o edad
- Videos privados no funcionarán

### Error: "No se pudo transcribir el audio"
- Verifica tu API key de OpenRouter
- Verifica que tengas créditos en OpenRouter
- El video puede ser muy largo (limitado a ~2 horas)

### La aplicación no inicia
- Verifica que FFmpeg esté instalado: `ffmpeg -version`
- Verifica que todas las variables de entorno estén configuradas
- Revisa los logs para más detalles

### Docker: Error de construcción
- Asegúrate de tener Docker y Docker Compose instalados
- Verifica que el puerto 8000 no esté en uso
- Ejecuta `docker-compose logs` para ver errores

## 🔗 Enlaces Útiles

- [OpenRouter](https://openrouter.ai/) - Obtén tu API key
- [OpenRouter Pricing](https://openrouter.ai/docs#models) - Precios de modelos
- [Dokploy](https://dokploy.com/) - Plataforma de deployment
- [FastAPI Docs](https://fastapi.tiangolo.com/) - Documentación de FastAPI

## 📝 Notas

- Los subtítulos automáticos de YouTube pueden tener errores de transcripción
- La calidad del resumen depende del modelo elegido
- Videos muy largos (>2 horas) pueden tardar más en procesar
- Algunos videos pueden no estar disponibles según tu región

## 🚧 Roadmap Futuro

- [ ] Soporte para múltiples idiomas de salida
- [ ] Guardar historial de resúmenes
- [ ] Modo "ultra económico" con modelos locales
- [ ] Soporte para playlists
- [ ] API de integración con Notion/Obsidian
- [ ] Generación de timestamps importantes

## 📄 Licencia

MIT

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor abre un issue o PR.

---

Hecho con ❤️ para mantenerse al día con YouTube sin gastar una fortuna en APIs.
