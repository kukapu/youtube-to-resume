# Guía de Despliegue en Dokploy

Esta guía explica cómo desplegar la aplicación YouTube Summarizer en Dokploy usando GitHub Actions para CI/CD.

## Requisitos Previos

1. Base de datos PostgreSQL creada en Dokploy
2. Repositorio en GitHub
3. Dokploy configurado y accesible

## Configuración

### 1. Base de Datos

Ya tienes la base de datos configurada en Dokploy:
```
postgresql://onizuka:onizuka@youtuberesume-postgresdb-b3hnej:5432/resumes
```

### 2. Variables de Entorno en Dokploy

Configura las siguientes variables de entorno en tu servicio de Dokploy:

#### Variables Requeridas:
```bash
OPENROUTER_API_KEY=tu_api_key_de_openrouter
DATABASE_URL=postgresql://onizuka:onizuka@youtuberesume-postgresdb-b3hnej:5432/resumes
```

#### Variables Opcionales:
```bash
GROQ_API_KEY=tu_groq_api_key
OPENAI_API_KEY=tu_openai_api_key
SUMMARY_MODEL=openai/gpt-4o-mini
TRANSCRIPTION_MODEL=openai/whisper-large-v3
PORT=8000
DOCKER_IMAGE=ghcr.io/TU_USUARIO/youtube-to-resume:latest
```

### 3. Configurar GitHub Actions

El workflow ya está configurado en `.github/workflows/docker-build.yml`. Se ejecutará automáticamente cuando:
- Hagas push a la rama `main`
- Crees un tag con el formato `v*.*.*` (ej: `v1.0.0`)

#### Pasos para activar el CI/CD:

1. **Habilitar GitHub Container Registry (GHCR)**:
   - Los permisos ya están configurados en el workflow
   - GitHub Actions usará `GITHUB_TOKEN` automáticamente

2. **Hacer push de los cambios**:
   ```bash
   git add .
   git commit -m "Add production deployment configuration"
   git push origin main
   ```

3. **Esperar a que se compile la imagen**:
   - Ve a la pestaña "Actions" en tu repositorio de GitHub
   - Verás el workflow "Build and Push Docker Image" ejecutándose
   - Espera a que termine (puede tardar 2-5 minutos)

4. **Verificar que la imagen se ha creado**:
   - Ve a la página principal de tu repositorio en GitHub
   - En el menú de la derecha, busca "Packages"
   - Deberías ver el package `youtube-to-resume`

### 4. Configurar Dokploy

#### Opción A: Usando Docker Compose (Recomendado)

1. En Dokploy, crea un nuevo servicio de tipo "Docker Compose"
2. Sube el archivo `compose.yml` de este repositorio
3. Configura las variables de entorno mencionadas anteriormente
4. Despliega el servicio

#### Opción B: Usando imagen Docker directamente

1. En Dokploy, crea un nuevo servicio de tipo "Docker"
2. Configura la imagen: `ghcr.io/TU_USUARIO/youtube-to-resume:latest`
3. Expón el puerto `8000`
4. Configura las variables de entorno
5. Despliega el servicio

### 5. Actualizar el Despliegue

Cada vez que hagas push a la rama `main`:

1. GitHub Actions compilará automáticamente una nueva imagen
2. La imagen se subirá a GHCR con el tag `latest`
3. Las imágenes antiguas se limpiarán automáticamente (se mantienen las últimas 3)

Para actualizar en Dokploy:
- Si configuraste el servicio correctamente, Dokploy puede detectar automáticamente las nuevas imágenes
- O puedes hacer un "Redeploy" manual desde el panel de Dokploy

### 6. Crear Versiones con Tags

Para crear versiones específicas:

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

Esto creará las siguientes imágenes:
- `ghcr.io/TU_USUARIO/youtube-to-resume:latest`
- `ghcr.io/TU_USUARIO/youtube-to-resume:v1.0.0`
- `ghcr.io/TU_USUARIO/youtube-to-resume:1.0`
- `ghcr.io/TU_USUARIO/youtube-to-resume:1`

## Limpieza Automática de Imágenes

El workflow está configurado para mantener solo las últimas 3 versiones de imágenes en GHCR. Esto ayuda a:
- Ahorrar espacio en el registro
- Mantener el registro limpio y organizado
- Reducir costos si tienes límites de almacenamiento

## Verificación del Despliegue

Una vez desplegado, verifica que funciona correctamente:

1. **Health Check**:
   ```bash
   curl https://tu-dominio.com/health
   ```
   Debería responder: `{"status":"ok"}`

2. **Interfaz Web**:
   - Visita `https://tu-dominio.com`
   - Deberías ver la interfaz de YouTube Summarizer

3. **Logs**:
   - Revisa los logs en Dokploy para verificar que la base de datos se conectó correctamente
   - Busca el mensaje: "✓ Base de datos inicializada"

## Solución de Problemas

### La imagen no se encuentra
- Verifica que el package en GitHub sea público o que Dokploy tenga acceso
- Para hacer el package público: Settings → Packages → Change visibility → Public

### Error de conexión a la base de datos
- Verifica que la `DATABASE_URL` sea correcta
- Asegúrate de que el contenedor tenga acceso a la red de la base de datos en Dokploy

### El workflow falla
- Revisa los logs en la pestaña "Actions" de GitHub
- Verifica que no haya errores en el Dockerfile

## Desarrollo Local

Para probar localmente:

```bash
# Copiar .env.example a .env y configurar variables
cp .env.example .env

# Usar docker-compose local
docker-compose -f compose.local.yml up
```

## Archivos Importantes

- `compose.yml`: Configuración para producción (Dokploy)
- `compose.local.yml`: Configuración para desarrollo local
- `.github/workflows/docker-build.yml`: Pipeline de CI/CD
- `Dockerfile`: Definición de la imagen Docker
- `.env.example`: Plantilla de variables de entorno
