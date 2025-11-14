# Actualización: Base de Datos PostgreSQL

## Cambios Implementados

Se ha añadido persistencia de datos usando **PostgreSQL** en un contenedor Docker. Ahora todos los resúmenes se guardan en la base de datos en lugar de localStorage del navegador.

### Nuevas Características

1. **Persistencia Real**: Los resúmenes se guardan en PostgreSQL y persisten incluso si se borra el caché del navegador
2. **Cache Inteligente**: Si solicitas el resumen de un video que ya procesaste, se devuelve instantáneamente desde la BD
3. **Historial Centralizado**: El historial ahora está en el servidor, accesible desde cualquier dispositivo
4. **Volumen Persistente**: Los datos de PostgreSQL se guardan en un volumen Docker (`postgres_data`)

## Arquitectura

```
┌─────────────────┐
│   Frontend      │
│  (index.html)   │
└────────┬────────┘
         │ HTTP API
         ↓
┌─────────────────┐
│   Backend       │
│  (FastAPI)      │
└────────┬────────┘
         │ SQLAlchemy
         ↓
┌─────────────────┐
│   PostgreSQL    │
│   (Container)   │
└─────────────────┘
```

## Nuevos Endpoints API

### `GET /api/summaries`
Obtiene el historial de resúmenes (máximo 50, ordenados por fecha)

**Respuesta:**
```json
[
  {
    "video_id": "dQw4w9WgXcQ",
    "title": "Título del Video",
    "created_at": "2025-11-14T21:00:00"
  }
]
```

### `GET /api/summaries/{video_id}`
Obtiene un resumen específico

**Respuesta:**
```json
{
  "video_id": "dQw4w9WgXcQ",
  "title": "Título del Video",
  "transcript_method": "subtitles",
  "summary": "# Resumen...",
  "cost_estimate": "~$0.001 - $0.002",
  "created_at": "2025-11-14T21:00:00"
}
```

### `DELETE /api/summaries/{video_id}`
Elimina un resumen específico

### `DELETE /api/summaries`
Elimina todos los resúmenes

## Esquema de Base de Datos

### Tabla: `summaries`

| Campo             | Tipo         | Descripción                          |
|-------------------|--------------|--------------------------------------|
| id                | INTEGER      | Primary Key                          |
| video_id          | VARCHAR(20)  | ID del video (único, indexado)       |
| title             | VARCHAR(500) | Título del video                     |
| transcript_method | VARCHAR(50)  | "subtitles" o "transcription"        |
| summary           | TEXT         | Resumen generado                     |
| cost_estimate     | VARCHAR(100) | Estimación de costo                  |
| created_at        | DATETIME     | Fecha de creación                    |

## Uso

### Iniciar con Docker Compose

```bash
docker-compose up -d
```

El contenedor de PostgreSQL se iniciará automáticamente y creará:
- Base de datos: `youtube_summaries`
- Usuario: `youtube_user`
- Contraseña: `youtube_pass`
- Puerto: `5432`

### Variables de Entorno

Añade a tu `.env`:

```bash
DATABASE_URL=postgresql://youtube_user:youtube_pass@db:5432/youtube_summaries
```

Para desarrollo local (sin Docker):
```bash
DATABASE_URL=postgresql://youtube_user:youtube_pass@localhost:5432/youtube_summaries
```

### Acceso Directo a PostgreSQL

```bash
# Conectarse al contenedor
docker exec -it youtube-summarizer-db psql -U youtube_user -d youtube_summaries

# Ver resúmenes
SELECT video_id, title, created_at FROM summaries ORDER BY created_at DESC;

# Salir
\q
```

## Migración desde localStorage

Si tenías resúmenes guardados en localStorage, estos NO se migrarán automáticamente a la base de datos. Simplemente procesa los videos nuevamente y se guardarán en la BD.

## Backup de Datos

### Crear backup
```bash
docker exec youtube-summarizer-db pg_dump -U youtube_user youtube_summaries > backup.sql
```

### Restaurar backup
```bash
cat backup.sql | docker exec -i youtube-summarizer-db psql -U youtube_user -d youtube_summaries
```

## Beneficios

✅ **Persistencia real**: Los datos no se pierden al limpiar el navegador
✅ **Cache de resúmenes**: Evita regenerar resúmenes de videos ya procesados
✅ **Multi-dispositivo**: Accede al historial desde cualquier navegador
✅ **Backup fácil**: Los datos están centralizados en PostgreSQL
✅ **Escalable**: PostgreSQL puede manejar miles de resúmenes sin problemas

## Troubleshooting

### El contenedor de BD no inicia
```bash
# Ver logs
docker logs youtube-summarizer-db

# Verificar que el puerto 5432 no esté ocupado
sudo lsof -i :5432
```

### Error de conexión a la base de datos
```bash
# Verificar que el contenedor esté corriendo
docker ps | grep postgres

# Verificar conectividad
docker exec youtube-summarizer-db pg_isready -U youtube_user
```

### Reiniciar la base de datos
```bash
# Eliminar el volumen (⚠️ PERDERÁS TODOS LOS DATOS)
docker-compose down -v
docker-compose up -d
```
