import os
import tempfile
import re
from typing import Optional, List
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from pydantic_settings import BaseSettings
from sqlalchemy.orm import Session
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable
)
import yt_dlp
import httpx

from database import get_db, init_db, Summary as DBSummary


class Settings(BaseSettings):
    openrouter_api_key: str
    summary_model: str = "openai/gpt-4o-mini"
    transcription_model: str = "openai/whisper-large-v3"
    groq_api_key: str = ""
    openai_api_key: str = ""
    port: int = 8000

    class Config:
        env_file = ".env"


settings = Settings()
app = FastAPI(title="YouTube Video Summarizer")

# Inicializar la base de datos al iniciar la aplicación
@app.on_event("startup")
async def startup_event():
    init_db()
    print("✓ Base de datos inicializada")


class VideoRequest(BaseModel):
    url: HttpUrl
    language: str = "es"


class SummaryResponse(BaseModel):
    video_id: str
    title: str
    transcript_method: str  # "subtitles" o "transcription"
    summary: str
    cost_estimate: str
    created_at: Optional[datetime] = None


class SummaryListItem(BaseModel):
    video_id: str
    title: str
    created_at: datetime
    
    class Config:
        from_attributes = True


def extract_video_id(url: str) -> Optional[str]:
    """Extrae el ID del video de una URL de YouTube."""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'^([0-9A-Za-z_-]{11})$'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_subtitles(video_id: str, language: str = "es") -> Optional[str]:
    """
    Intenta obtener los subtítulos del video usando yt-dlp.
    Esto es más robusto que youtube-transcript-api.
    """
    try:
        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': [language, 'en'],
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            # Intentar obtener subtítulos en el idioma solicitado
            if 'subtitles' in info and info['subtitles']:
                if language in info['subtitles']:
                    subtitle_data = info['subtitles'][language]
                    if subtitle_data and len(subtitle_data) > 0:
                        # Descargar el primer formato disponible
                        subtitle_url = subtitle_data[0]['url']
                        import requests
                        response = requests.get(subtitle_url)
                        if response.status_code == 200:
                            # Parsear el contenido (puede ser VTT o SRT)
                            text = parse_subtitle_content(response.text)
                            if text:
                                char_count = len(text)
                                word_count = len(text.split())
                                print(f"✓ Subtítulos manuales obtenidos en {language} ({word_count} palabras, {char_count} caracteres)")
                                return text
                
                # Intentar inglés si no está en el idioma solicitado
                if 'en' in info['subtitles']:
                    subtitle_data = info['subtitles']['en']
                    if subtitle_data and len(subtitle_data) > 0:
                        subtitle_url = subtitle_data[0]['url']
                        import requests
                        response = requests.get(subtitle_url)
                        if response.status_code == 200:
                            text = parse_subtitle_content(response.text)
                            if text:
                                char_count = len(text)
                                word_count = len(text.split())
                                print(f"✓ Subtítulos manuales obtenidos en inglés ({word_count} palabras, {char_count} caracteres)")
                                return text
            
            # Intentar con subtítulos automáticos
            if 'automatic_captions' in info and info['automatic_captions']:
                for lang in [language, 'en']:
                    if lang in info['automatic_captions']:
                        subtitle_data = info['automatic_captions'][lang]
                        if subtitle_data and len(subtitle_data) > 0:
                            subtitle_url = subtitle_data[0]['url']
                            import requests
                            response = requests.get(subtitle_url)
                            if response.status_code == 200:
                                text = parse_subtitle_content(response.text)
                                if text:
                                    char_count = len(text)
                                    word_count = len(text.split())
                                    print(f"✓ Subtítulos automáticos obtenidos en {lang} ({word_count} palabras, {char_count} caracteres)")
                                    return text
        
        return None
    except Exception as e:
        print(f"Error obteniendo subtítulos: {e}")
        return None


def parse_subtitle_content(content: str) -> Optional[str]:
    """Parsea el contenido de subtítulos (VTT o SRT) y extrae solo el texto."""
    try:
        lines = content.split('\n')
        text_lines = []
        
        for line in lines:
            line = line.strip()
            # Saltar líneas vacías, marcadores de tiempo y headers
            if not line or line.startswith('WEBVTT') or '-->' in line or line.isdigit():
                continue
            # Saltar etiquetas de formato
            if line.startswith('<') or line.startswith('['):
                continue
            text_lines.append(line)
        
        return ' '.join(text_lines)
    except Exception as e:
        print(f"Error parseando subtítulos: {e}")
        return None


def download_audio(video_id: str, max_size_mb: int = 24) -> Optional[tuple[str, float]]:
    """Descarga el audio del video optimizado para APIs.
    
    Returns:
        tuple: (audio_path, file_size_mb) o None
    """
    try:
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, f"{video_id}.mp3")

        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '32',  # Muy baja calidad para reducir tamaño
            }],
            'outtmpl': os.path.join(temp_dir, f"{video_id}.%(ext)s"),
            'quiet': True,
            'no_warnings': True,
            # Opciones para evitar bloqueo 403
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['webpage', 'configs'],
                }
            },
            'nocheckcertificate': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        if os.path.exists(output_path):
            file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"📁 Audio descargado: {file_size_mb:.2f}MB")
            
            if file_size_mb > max_size_mb:
                print(f"⚠️ Archivo muy grande ({file_size_mb:.2f}MB), comprimiendo...")
                # Intentar comprimir más
                compressed_path = compress_audio(output_path, target_mb=max_size_mb)
                if compressed_path:
                    os.remove(output_path)
                    return compressed_path, os.path.getsize(compressed_path) / (1024 * 1024)
            
            return output_path, file_size_mb
        
        return None
    except Exception as e:
        print(f"Error descargando audio: {e}")
        return None


def compress_audio(input_path: str, target_mb: int = 24) -> Optional[str]:
    """Comprime el audio para que quepa en el límite de la API."""
    try:
        import subprocess
        output_path = input_path.replace('.mp3', '_compressed.mp3')

        # Usar ffmpeg para comprimir a calidad muy baja
        cmd = [
            'ffmpeg', '-i', input_path,
            '-ab', '24k',  # Bitrate muy bajo
            '-ar', '16000',  # Sample rate bajo
            '-ac', '1',  # Mono
            '-y', output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0 and os.path.exists(output_path):
            new_size = os.path.getsize(output_path) / (1024 * 1024)
            print(f"✓ Audio comprimido a {new_size:.2f}MB")
            return output_path

        return None
    except Exception as e:
        print(f"Error comprimiendo audio: {e}")
        return None


def get_audio_duration(audio_path: str) -> Optional[float]:
    """Obtiene la duración del audio en segundos usando ffprobe."""
    try:
        import subprocess
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            duration = float(result.stdout.strip())
            return duration

        return None
    except Exception as e:
        print(f"Error obteniendo duración del audio: {e}")
        return None


def split_audio_into_chunks(audio_path: str, chunk_duration_sec: int = 600) -> List[str]:
    """
    Divide un archivo de audio en chunks usando ffmpeg.

    Args:
        audio_path: Ruta al archivo de audio
        chunk_duration_sec: Duración de cada chunk en segundos (default: 10 minutos)

    Returns:
        Lista de rutas a los archivos de chunks
    """
    try:
        import subprocess

        # Obtener duración total
        total_duration = get_audio_duration(audio_path)
        if not total_duration:
            print("⚠️ No se pudo obtener duración, usando archivo completo")
            return [audio_path]

        # Si el audio es más corto que chunk_duration, devolver el archivo original
        if total_duration <= chunk_duration_sec:
            return [audio_path]

        # Calcular número de chunks
        num_chunks = int(total_duration / chunk_duration_sec) + 1
        print(f"📂 Dividiendo audio de {total_duration:.0f}s en {num_chunks} chunks de {chunk_duration_sec}s")

        # Dividir en chunks
        temp_dir = os.path.dirname(audio_path)
        base_name = os.path.splitext(os.path.basename(audio_path))[0]
        chunks = []

        for i in range(num_chunks):
            start_time = i * chunk_duration_sec
            chunk_path = os.path.join(temp_dir, f"{base_name}_chunk_{i}.mp3")

            cmd = [
                'ffmpeg',
                '-i', audio_path,
                '-ss', str(start_time),
                '-t', str(chunk_duration_sec),
                '-c', 'copy',  # Copiar sin re-encodear (más rápido)
                '-y',
                chunk_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0 and os.path.exists(chunk_path):
                chunk_size = os.path.getsize(chunk_path) / (1024 * 1024)
                print(f"  ✓ Chunk {i+1}/{num_chunks}: {chunk_size:.2f}MB")
                chunks.append(chunk_path)
            else:
                print(f"  ⚠️ Error creando chunk {i+1}")

        return chunks if chunks else [audio_path]

    except Exception as e:
        print(f"Error dividiendo audio en chunks: {e}")
        return [audio_path]


async def transcribe_with_groq(audio_path: str) -> Optional[str]:
    """Transcribe el audio usando Groq Whisper (GRATIS y rápido)."""
    if not settings.groq_api_key:
        print("⚠️ GROQ_API_KEY no configurada")
        return None
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(audio_path, 'rb') as audio_file:
                files = {'file': (os.path.basename(audio_path), audio_file, 'audio/mpeg')}
                data = {
                    'model': 'whisper-large-v3',
                    'language': 'es',
                    'response_format': 'json'
                }
                headers = {
                    'Authorization': f'Bearer {settings.groq_api_key}',
                }

                print("🎤 Transcribiendo con Groq (gratis)...")
                response = await client.post(
                    'https://api.groq.com/openai/v1/audio/transcriptions',
                    files=files,
                    data=data,
                    headers=headers
                )

                if response.status_code == 200:
                    result = response.json()
                    text = result.get('text')
                    if text:
                        print(f"✓ Transcripción completada con Groq ({len(text)} caracteres)")
                        return text
                else:
                    print(f"⚠️ Error en Groq: {response.status_code} - {response.text}")
                    return None
    except Exception as e:
        print(f"⚠️ Error con Groq: {e}")
        return None


async def transcribe_with_openai(audio_path: str) -> Optional[str]:
    """Transcribe el audio usando OpenAI Whisper (fallback, de pago)."""
    if not settings.openai_api_key:
        print("⚠️ OPENAI_API_KEY no configurada")
        return None
    
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(audio_path, 'rb') as audio_file:
                files = {'file': (os.path.basename(audio_path), audio_file, 'audio/mpeg')}
                data = {
                    'model': 'whisper-1',
                    'language': 'es'
                }
                headers = {
                    'Authorization': f'Bearer {settings.openai_api_key}',
                }

                print("🎤 Transcribiendo con OpenAI Whisper...")
                response = await client.post(
                    'https://api.openai.com/v1/audio/transcriptions',
                    files=files,
                    data=data,
                    headers=headers
                )

                if response.status_code == 200:
                    result = response.json()
                    text = result.get('text')
                    if text:
                        print(f"✓ Transcripción completada con OpenAI ({len(text)} caracteres)")
                        return text
                else:
                    print(f"⚠️ Error en OpenAI: {response.status_code} - {response.text}")
                    return None
    except Exception as e:
        print(f"⚠️ Error con OpenAI: {e}")
        return None


async def transcribe_audio_with_whisper(audio_path: str, file_size_mb: float) -> Optional[str]:
    """Transcribe el audio usando Groq (gratis) o OpenAI como fallback.

    Si el archivo es > 25MB, lo divide en chunks y transcribe cada uno por separado.
    """
    chunks_to_cleanup = []

    try:
        # Si el archivo es muy grande, dividir en chunks
        if file_size_mb > 25:
            print(f"⚠️ Archivo grande ({file_size_mb:.2f}MB), dividiendo en chunks...")
            chunks = split_audio_into_chunks(audio_path, chunk_duration_sec=600)  # 10 minutos

            if len(chunks) == 1 and chunks[0] == audio_path:
                # No se pudo dividir, el archivo sigue siendo muy grande
                print(f"❌ No se pudo dividir el archivo, sigue siendo muy grande")
                return None

            chunks_to_cleanup = [c for c in chunks if c != audio_path]
        else:
            # Archivo pequeño, usar directamente
            chunks = [audio_path]

        # Transcribir cada chunk
        transcripts = []

        for i, chunk_path in enumerate(chunks):
            chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)

            # Verificar que el chunk no sea muy grande
            if chunk_size_mb > 25:
                print(f"⚠️ Chunk {i+1} muy grande ({chunk_size_mb:.2f}MB), saltando...")
                continue

            print(f"🎤 Transcribiendo chunk {i+1}/{len(chunks)} ({chunk_size_mb:.2f}MB)...")

            # Intentar con Groq primero (gratis)
            transcript = await transcribe_with_groq(chunk_path)

            # Si Groq falla, intentar con OpenAI
            if not transcript:
                print(f"⚠️ Groq falló para chunk {i+1}, intentando con OpenAI...")
                transcript = await transcribe_with_openai(chunk_path)

            if transcript:
                transcripts.append(transcript)
                print(f"✓ Chunk {i+1}/{len(chunks)} transcrito ({len(transcript)} caracteres)")
            else:
                print(f"⚠️ No se pudo transcribir chunk {i+1}")

        if not transcripts:
            print("❌ No se pudo transcribir ningún chunk")
            return None

        # Combinar todas las transcripciones
        full_transcript = " ".join(transcripts)
        print(f"✓ Transcripción completa: {len(full_transcript)} caracteres de {len(chunks)} chunks")

        return full_transcript

    except Exception as e:
        print(f"Error transcribiendo audio: {e}")
        return None
    finally:
        # Limpiar archivos temporales
        try:
            # Limpiar archivo original
            if os.path.exists(audio_path):
                os.remove(audio_path)

            # Limpiar chunks
            for chunk_path in chunks_to_cleanup:
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)

            # Limpiar versiones comprimidas
            compressed = audio_path.replace('.mp3', '_compressed.mp3')
            if os.path.exists(compressed):
                os.remove(compressed)

            # Limpiar directorio temporal
            temp_dir = os.path.dirname(audio_path)
            if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                os.rmdir(temp_dir)

        except Exception as cleanup_error:
            print(f"Error limpiando archivos: {cleanup_error}")


async def generate_summary(text: str, language: str = "es") -> str:
    """Genera un resumen usando OpenRouter."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            prompt = f"""Eres un experto en crear resúmenes detallados de videos de YouTube. Tu objetivo es que la persona que lea el resumen comprenda completamente el contenido del video, casi como si lo hubiera visto.

Analiza el siguiente texto (transcripción completa de un video de YouTube) y genera un resumen DETALLADO en español que incluya:

1. **Introducción y contexto**: ¿De qué trata el video? ¿Cuál es el tema principal y por qué es importante?

2. **Desarrollo completo**: Explica TODO el contenido del video de forma estructurada y cronológica. Incluye:
   - Todos los conceptos importantes explicados
   - Ejemplos mencionados
   - Argumentos y razonamientos presentados
   - Procesos o pasos descritos
   - Historias o anécdotas relevantes

3. **Datos y cifras**: Cualquier estadística, número, fecha o dato específico mencionado

4. **Conclusiones y puntos clave**: Las ideas principales y mensajes finales del video

5. **Información práctica**: Si hay consejos, recomendaciones o aplicaciones prácticas, menciónalos

REQUISITOS:
- Sé DETALLADO y exhaustivo, no te limites a puntos generales
- Usa un tono claro y natural, como si estuvieras explicándoselo a alguien
- Organiza el contenido con subtítulos, listas y párrafos según sea necesario
- Usa markdown para el formato
- Si el video tiene secciones claras, respeta esa estructura
- NO omitas información importante, queremos capturar TODO el valor del video

TEXTO DE LA TRANSCRIPCIÓN:
{text[:30000]}

Genera el resumen DETALLADO en ESPAÑOL:"""

            response = await client.post(
                'https://openrouter.ai/api/v1/chat/completions',
                json={
                    'model': settings.summary_model,
                    'messages': [
                        {'role': 'user', 'content': prompt}
                    ],
                    'temperature': 0.7,
                    'max_tokens': 4000
                },
                headers={
                    'Authorization': f'Bearer {settings.openrouter_api_key}',
                    'HTTP-Referer': 'http://localhost:8000',
                    'X-Title': 'YouTube Summarizer'
                }
            )

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Error al generar resumen: {response.text}"
                )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al generar resumen: {str(e)}"
        )


def get_video_info(video_id: str) -> dict:
    """Obtiene información básica del video."""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            # Opciones para evitar bloqueo 403
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['webpage', 'configs'],
                }
            },
            'nocheckcertificate': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False
            )
            return {
                'title': info.get('title', 'Sin título'),
                'duration': info.get('duration', 0),
                'channel': info.get('channel', 'Desconocido')
            }
    except Exception as e:
        print(f"Error obteniendo info del video: {e}")
        return {
            'title': 'Video de YouTube',
            'duration': 0,
            'channel': 'Desconocido'
        }


@app.post("/api/summarize", response_model=SummaryResponse)
async def summarize_video(request: VideoRequest, db: Session = Depends(get_db)):
    """
    Procesa una URL de YouTube y devuelve un resumen del contenido.
    """
    # Extraer video ID
    video_id = extract_video_id(str(request.url))
    if not video_id:
        raise HTTPException(status_code=400, detail="URL de YouTube inválida")

    # Verificar si ya existe en la base de datos
    existing_summary = db.query(DBSummary).filter(DBSummary.video_id == video_id).first()
    if existing_summary:
        print(f"✓ Resumen encontrado en base de datos para {video_id}")
        return SummaryResponse(
            video_id=existing_summary.video_id,
            title=existing_summary.title,
            transcript_method=existing_summary.transcript_method,
            summary=existing_summary.summary,
            cost_estimate=existing_summary.cost_estimate,
            created_at=existing_summary.created_at
        )

    # Obtener información del video
    video_info = get_video_info(video_id)

    # Intentar obtener subtítulos primero (GRATIS)
    print(f"Intentando obtener subtítulos para {video_id}...")
    transcript = get_subtitles(video_id, request.language)
    transcript_method = "subtitles"

    # Si no hay subtítulos, descargar y transcribir audio
    if not transcript:
        print(f"No hay subtítulos disponibles. Descargando audio...")
        audio_result = download_audio(video_id)

        if not audio_result:
            raise HTTPException(
                status_code=500,
                detail="No se pudo obtener el contenido del video (sin subtítulos ni audio disponible)"
            )
        
        audio_path, file_size_mb = audio_result
        print(f"Transcribiendo audio...")
        transcript = await transcribe_audio_with_whisper(audio_path, file_size_mb)
        transcript_method = "transcription"

        if not transcript:
            raise HTTPException(
                status_code=500,
                detail="No se pudo transcribir el audio del video"
            )

    # Generar resumen
    print(f"Generando resumen...")
    summary = await generate_summary(transcript, request.language)

    # Estimar costo
    if transcript_method == "subtitles":
        cost_estimate = "~$0.001 - $0.002 (solo resumen)"
    else:
        cost_estimate = "~$0.01 - $0.03 (transcripción + resumen)"

    # Guardar en la base de datos
    db_summary = DBSummary(
        video_id=video_id,
        title=video_info['title'],
        transcript_method=transcript_method,
        summary=summary,
        cost_estimate=cost_estimate
    )
    db.add(db_summary)
    db.commit()
    db.refresh(db_summary)
    print(f"✓ Resumen guardado en base de datos")

    return SummaryResponse(
        video_id=video_id,
        title=video_info['title'],
        transcript_method=transcript_method,
        summary=summary,
        cost_estimate=cost_estimate,
        created_at=db_summary.created_at
    )


@app.get("/api/summaries", response_model=List[SummaryListItem])
async def get_summaries(limit: int = 50, db: Session = Depends(get_db)):
    """
    Obtiene el historial de resúmenes guardados.
    """
    summaries = db.query(DBSummary).order_by(DBSummary.created_at.desc()).limit(limit).all()
    return summaries


@app.get("/api/summaries/{video_id}", response_model=SummaryResponse)
async def get_summary(video_id: str, db: Session = Depends(get_db)):
    """
    Obtiene un resumen específico por video_id.
    """
    summary = db.query(DBSummary).filter(DBSummary.video_id == video_id).first()
    if not summary:
        raise HTTPException(status_code=404, detail="Resumen no encontrado")
    
    return SummaryResponse(
        video_id=summary.video_id,
        title=summary.title,
        transcript_method=summary.transcript_method,
        summary=summary.summary,
        cost_estimate=summary.cost_estimate,
        created_at=summary.created_at
    )


@app.delete("/api/summaries/{video_id}")
async def delete_summary(video_id: str, db: Session = Depends(get_db)):
    """
    Elimina un resumen específico.
    """
    summary = db.query(DBSummary).filter(DBSummary.video_id == video_id).first()
    if not summary:
        raise HTTPException(status_code=404, detail="Resumen no encontrado")
    
    db.delete(summary)
    db.commit()
    return {"message": "Resumen eliminado"}


@app.delete("/api/summaries")
async def delete_all_summaries(db: Session = Depends(get_db)):
    """
    Elimina todos los resúmenes.
    """
    db.query(DBSummary).delete()
    db.commit()
    return {"message": "Todos los resúmenes eliminados"}


@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Sirve el frontend."""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            return f.read()
    return """
    <html>
        <head>
            <title>YouTube Summarizer</title>
        </head>
        <body>
            <h1>YouTube Summarizer</h1>
            <p>Frontend no encontrado. Usa la API en /api/summarize</p>
        </body>
    </html>
    """


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
