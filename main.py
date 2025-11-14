import os
import tempfile
import re
from typing import Optional
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

        return output_path if os.path.exists(output_path) else None
    except Exception as e:
        print(f"Error descargando audio: {e}")
        return None


async def transcribe_audio(audio_path: str) -> Optional[str]:
    """Transcribe el audio usando OpenRouter (Whisper)."""
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(audio_path, 'rb') as audio_file:
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
        print(f"Error transcribiendo audio: {e}")
        return None
    finally:
        # Limpiar archivo temporal
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
