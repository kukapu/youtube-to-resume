import os
import tempfile
import re
from typing import Optional, List
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from pydantic_settings import BaseSettings
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable
)
import yt_dlp
import httpx
from pydub import AudioSegment


class Settings(BaseSettings):
    openrouter_api_key: str
    summary_model: str = "openai/gpt-4o-mini"
    transcription_model: str = "openai/whisper-large-v3"
    port: int = 8000

    class Config:
        env_file = ".env"


settings = Settings()
app = FastAPI(title="YouTube Video Summarizer")


class VideoRequest(BaseModel):
    url: HttpUrl
    language: str = "es"


class SummaryResponse(BaseModel):
    video_id: str
    title: str
    transcript_method: str  # "subtitles" o "transcription"
    summary: str
    cost_estimate: str


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
    Intenta obtener los subtítulos del video.
    Primero busca en español, luego en inglés, y finalmente en cualquier idioma disponible.
    """
    try:
        # Intentar obtener lista de transcripciones disponibles
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Intentar obtener transcripción en el idioma solicitado
        try:
            transcript = transcript_list.find_transcript([language])
            text = " ".join([entry['text'] for entry in transcript.fetch()])
            return text
        except NoTranscriptFound:
            pass

        # Si no está en español, intentar en inglés
        if language != "en":
            try:
                transcript = transcript_list.find_transcript(['en'])
                text = " ".join([entry['text'] for entry in transcript.fetch()])
                return text
            except NoTranscriptFound:
                pass

        # Si no, tomar el primer idioma disponible
        try:
            transcript = transcript_list.find_generated_transcript(['en', 'es', 'auto'])
            text = " ".join([entry['text'] for entry in transcript.fetch()])
            return text
        except:
            pass

        # Último intento: cualquier transcripción manual
        for transcript in transcript_list:
            if not transcript.is_generated:
                text = " ".join([entry['text'] for entry in transcript.fetch()])
                return text

        # Último último intento: cualquier transcripción
        for transcript in transcript_list:
            text = " ".join([entry['text'] for entry in transcript.fetch()])
            return text

    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return None
    except Exception as e:
        print(f"Error obteniendo subtítulos: {e}")
        return None


def download_audio(video_id: str) -> Optional[str]:
    """Descarga el audio del video y devuelve la ruta del archivo."""
    try:
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, f"{video_id}.mp3")

        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '64',  # Baja calidad para ahorrar
            }],
            'outtmpl': os.path.join(temp_dir, f"{video_id}.%(ext)s"),
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        return output_path if os.path.exists(output_path) else None
    except Exception as e:
        print(f"Error descargando audio: {e}")
        return None


def split_audio_into_chunks(audio_path: str, chunk_duration_ms: int = 600000) -> List[str]:
    """
    Divide un archivo de audio en chunks más pequeños.

    Args:
        audio_path: Ruta al archivo de audio
        chunk_duration_ms: Duración de cada chunk en milisegundos (default: 10 minutos)

    Returns:
        Lista de rutas a los archivos de chunks
    """
    try:
        # Cargar el audio
        audio = AudioSegment.from_mp3(audio_path)

        # Calcular número de chunks necesarios
        total_duration = len(audio)
        chunks = []

        # Si el audio es más corto que el chunk_duration, devolver el archivo original
        if total_duration <= chunk_duration_ms:
            return [audio_path]

        # Dividir en chunks
        temp_dir = os.path.dirname(audio_path)
        base_name = os.path.splitext(os.path.basename(audio_path))[0]

        for i, start_time in enumerate(range(0, total_duration, chunk_duration_ms)):
            end_time = min(start_time + chunk_duration_ms, total_duration)
            chunk = audio[start_time:end_time]

            chunk_path = os.path.join(temp_dir, f"{base_name}_chunk_{i}.mp3")
            chunk.export(chunk_path, format="mp3", bitrate="64k")
            chunks.append(chunk_path)

        print(f"Audio dividido en {len(chunks)} chunks")
        return chunks
    except Exception as e:
        print(f"Error dividiendo audio en chunks: {e}")
        return [audio_path]  # Si falla, devolver el archivo original


async def transcribe_audio_chunk(chunk_path: str) -> Optional[str]:
    """Transcribe un chunk de audio usando OpenRouter (Whisper)."""
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(chunk_path, 'rb') as audio_file:
                files = {'file': audio_file}
                data = {'model': settings.transcription_model}
                headers = {
                    'Authorization': f'Bearer {settings.openrouter_api_key}',
                }

                response = await client.post(
                    'https://openrouter.ai/api/v1/audio/transcriptions',
                    files=files,
                    data=data,
                    headers=headers
                )

                if response.status_code == 200:
                    result = response.json()
                    return result.get('text')
                else:
                    print(f"Error en transcripción: {response.status_code} - {response.text}")
                    return None
    except Exception as e:
        print(f"Error transcribiendo chunk: {e}")
        return None


async def transcribe_audio(audio_path: str) -> Optional[str]:
    """
    Transcribe el audio usando OpenRouter (Whisper).
    Si el archivo es muy grande, lo divide en chunks más pequeños.
    """
    try:
        # Verificar el tamaño del archivo
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        print(f"Tamaño del archivo de audio: {file_size_mb:.2f} MB")

        # Si el archivo es mayor a 20MB, dividirlo en chunks
        if file_size_mb > 20:
            print(f"Archivo muy grande ({file_size_mb:.2f} MB), dividiendo en chunks...")
            chunks = split_audio_into_chunks(audio_path, chunk_duration_ms=600000)  # 10 minutos
        else:
            chunks = [audio_path]

        # Transcribir cada chunk
        transcriptions = []
        for i, chunk_path in enumerate(chunks):
            print(f"Transcribiendo chunk {i+1}/{len(chunks)}...")
            transcription = await transcribe_audio_chunk(chunk_path)

            if transcription:
                transcriptions.append(transcription)
            else:
                print(f"Advertencia: No se pudo transcribir el chunk {i+1}")

            # Limpiar el chunk si no es el archivo original
            if chunk_path != audio_path:
                try:
                    os.remove(chunk_path)
                except:
                    pass

        # Combinar todas las transcripciones
        if transcriptions:
            full_transcription = " ".join(transcriptions)
            print(f"Transcripción completada: {len(full_transcription)} caracteres")
            return full_transcription
        else:
            return None

    except Exception as e:
        print(f"Error transcribiendo audio: {e}")
        return None
    finally:
        # Limpiar archivo temporal original
        try:
            os.remove(audio_path)
            os.rmdir(os.path.dirname(audio_path))
        except:
            pass


async def generate_summary(text: str, language: str = "es") -> str:
    """Genera un resumen usando OpenRouter."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            prompt = f"""Eres un experto en crear resúmenes concisos y útiles de videos.
Analiza el siguiente texto (transcripción de un video de YouTube) y genera un resumen en español que incluya:

1. **Tema principal**: Una frase que resuma de qué trata el video
2. **Puntos clave**: Los 5-7 puntos más importantes del video (usa viñetas)
3. **Conclusiones**: Las ideas principales o conclusiones del video
4. **Información relevante**: Cualquier dato, estadística o información específica que sea importante recordar

El resumen debe ser claro, estructurado y fácil de leer. Usa markdown para el formato.

TEXTO:
{text[:15000]}  # Limitamos a ~15k caracteres para evitar costos excesivos

Genera el resumen en ESPAÑOL."""

            response = await client.post(
                'https://openrouter.ai/api/v1/chat/completions',
                json={
                    'model': settings.summary_model,
                    'messages': [
                        {'role': 'user', 'content': prompt}
                    ],
                    'temperature': 0.7,
                    'max_tokens': 2000
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
async def summarize_video(request: VideoRequest):
    """
    Procesa una URL de YouTube y devuelve un resumen del contenido.
    """
    # Extraer video ID
    video_id = extract_video_id(str(request.url))
    if not video_id:
        raise HTTPException(status_code=400, detail="URL de YouTube inválida")

    # Obtener información del video
    video_info = get_video_info(video_id)

    # Intentar obtener subtítulos primero (GRATIS)
    print(f"Intentando obtener subtítulos para {video_id}...")
    transcript = get_subtitles(video_id, request.language)
    transcript_method = "subtitles"

    # Si no hay subtítulos, descargar y transcribir audio
    if not transcript:
        print(f"No hay subtítulos disponibles. Descargando audio...")
        audio_path = download_audio(video_id)

        if not audio_path:
            raise HTTPException(
                status_code=500,
                detail="No se pudo obtener el contenido del video (sin subtítulos ni audio disponible)"
            )

        print(f"Transcribiendo audio...")
        transcript = await transcribe_audio(audio_path)
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

    return SummaryResponse(
        video_id=video_id,
        title=video_info['title'],
        transcript_method=transcript_method,
        summary=summary,
        cost_estimate=cost_estimate
    )


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
