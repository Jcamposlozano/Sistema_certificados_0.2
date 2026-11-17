# Beta UCTS con Docker Compose y SQLite

La beta tiene dos contenedores. Nginx sirve Angular y reenvía `/api/*` y
`/health/*` a FastAPI en la red de Compose. FastAPI usa Cognito y el generador
PDF de `certificate-service`. El único puerto publicado es
`127.0.0.1:8000`.

## Archivos que utiliza la beta

| Ruta del equipo | Uso |
| --- | --- |
| `Backend/data/ucts_certificados.sqlite` | Catálogo de participantes y certificados que FastAPI abre en solo lectura. |
| `Backend/data/ucts_auth.sqlite` | Sesiones, desafíos, vínculos Cognito y auditoría de descargas. El directorio de datos se monta para conservar tanto la base como los archivos de transacción de SQLite. |
| `Backend/.env` | Región, User Pool, App Client y secretos del backend. Se lee al arrancar el contenedor. |
| `Backend/templates` | Plantillas UCTS montadas en solo lectura en `/templates`. |
| `../certificate-service/app` | Código del generador durante la construcción. |
| `~/.aws` | Configuración y credenciales locales leídas en modo de solo lectura. El perfil predeterminado es `ucts-cert-lab`. |

Si usas otra ubicación, puedes exportar `BETA_CERTIFICATE_SERVICE_DIR`,
`BETA_DATA_DIR`, `BETA_BACKEND_ENV_FILE` o `BETA_AWS_DIR` con rutas absolutas.
Para otro perfil, exporta `BETA_AWS_PROFILE`. El perfil requiere permisos
`AdminGetUser` y `AdminCreateUser` sobre el User Pool. Las bases, las plantillas
y las credenciales permanecen en el equipo.

## Construir y arrancar

1. Abre Docker Desktop.
2. Detén el proceso que ocupe el puerto 8000 con `Ctrl+C` en su terminal.
3. Desde la raíz del proyecto, ejecuta:

   ```bash
   export BETA_UID="$(id -u)" BETA_GID="$(id -g)"
   docker compose -f compose.beta.yaml up --build -d
   docker compose -f compose.beta.yaml logs -f
   ```

Los identificadores del usuario permiten que FastAPI escriba en los archivos
existentes de SQLite conservando sus permisos. El arranque comprueba que ambos
archivos existan y prepara de forma idempotente las tablas de autenticación y
auditoría. Esta beta usa el origen local HTTP y una sola instancia de FastAPI
sobre SQLite.

Abre `http://127.0.0.1:8000/health/ready` para comprobar el backend y
`http://127.0.0.1:8000/certificados` para entrar al portal. Prueba con un correo
principal que controles. Tras descargar un certificado, consulta
`certificate_downloads` en la base de autenticación con DBeaver.

Si estás trabajando con `npm start`, Angular en el puerto `4200` también puede
iniciar sesión con la beta por medio de su proxy de desarrollo al puerto `8000`.
FastAPI admite únicamente los orígenes locales `localhost` y `127.0.0.1` en
ambos puertos.

Para detener los contenedores desde la raíz del proyecto:

```bash
docker compose -f compose.beta.yaml down
```

Los datos y la auditoría persisten en `Backend/data/`. El Compose de PostgreSQL
vive en `Backend/compose.yaml` y se ejecuta por separado.

## Ejecutar en EC2 con Docker

En la instancia instala Docker Engine y Docker Compose 2.24.4 o posterior.
Poetry y Node se usan durante la construcción de las imágenes. En el servidor
necesitas el proyecto, `Backend/.env` con las variables de Cognito, los dos
SQLite en `Backend/data/`, `Backend/templates/` y el código del generador en
`../certificate-service/app`. Si el generador está en otra ruta, exporta
`BETA_CERTIFICATE_SERVICE_DIR` apuntando a su directorio padre.

Asocia a EC2 un rol de instancia con `cognito-idp:AdminGetUser` y
`cognito-idp:AdminCreateUser` sobre el User Pool. Con IMDSv2 habilitado, usa
un límite de saltos de 2 para que el contenedor pueda recibir las credenciales
temporales. [Configuración de IMDSv2 en EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-IMDS-new-instances.html)

Desde la raíz del proyecto en EC2:

```bash
export BETA_UID="$(id -u)" BETA_GID="$(id -g)"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
docker compose -f compose.beta.yaml -f compose.ec2.yaml up --build -d --wait
curl -fsS http://127.0.0.1:8000/health/ready
docker compose -f compose.beta.yaml -f compose.ec2.yaml logs -f
```

### Hosts y rutas en producción

`compose.ec2.yaml` establece `APP_ENV=production` y entrega `ALLOWED_HOSTS`
a FastAPI como una lista JSON. `TrustedHostMiddleware` compara esa lista con
el encabezado `Host`. Con la configuración predeterminada, los valores son
`["uctszone.net","api.uctszone.net","127.0.0.1","localhost","backend"]`.
Las variables `ALLOWED_HOSTS` y `ALLOWED_ORIGINS` del archivo `Backend/.env`
quedan reemplazadas por las del Compose de EC2.

`UCTS_PUBLIC_HOSTNAME` define el host del portal y, de forma independiente,
el origen HTTPS permitido por `ALLOWED_ORIGINS` para las solicitudes de
autenticación. Por defecto el portal usa `https://uctszone.net`. Si sirves
Angular y la API juntos desde `https://api.uctszone.net`, exporta
`UCTS_PUBLIC_HOSTNAME=api.uctszone.net` antes de ejecutar Compose y conserva ese
valor en el entorno de despliegue. Un alias permitido en `ALLOWED_HOSTS` por
sí solo no habilita peticiones de autenticación desde otro origen.

El Nginx del host debe conservar el encabezado original con
`proxy_set_header Host $http_host;` al reenviar a `http://127.0.0.1:8000`.
Nginx en Docker lo conserva también. La salud está en `GET /health/ready` y
las rutas del portal conservan el prefijo `/api`, por ejemplo `GET /api/me`
y `POST /api/auth/otp/request`. Accede a Angular y a `/api/` bajo el mismo
origen HTTPS para usar la sesión.

### Aplicar un cambio de hosts

Después de aprobar el PR, guarda una copia del Compose vigente **antes de
actualizar el código**. Ejecuta en EC2 desde la raíz del proyecto:

```bash
cd ~/Sistema_certificados_0.2
rollback_dir=$(mktemp -d "$HOME/ucts-hosts-rollback.XXXXXX")
cp -p compose.ec2.yaml "$rollback_dir/compose.ec2.yaml"
printf 'Copia de rollback: %s\n' "$rollback_dir/compose.ec2.yaml"
```

Actualiza a la revisión aprobada mediante tu procedimiento de entrega.
Si la entrega se hace copiando archivos, basta con transferir
`compose.ec2.yaml` para este cambio. Con las imágenes ya construidas, vuelve
a crear solo el backend para aplicar las variables nuevas:

```bash
export BETA_UID="$(id -u)" BETA_GID="$(id -g)"
unset AWS_PROFILE AWS_DEFAULT_PROFILE
docker compose -f compose.beta.yaml -f compose.ec2.yaml \
  up -d --no-deps --no-build --wait backend
```

Para reconstruir el backend en una instalación nueva o cuando también cambie
su código, ejecuta `docker compose -f compose.beta.yaml -f compose.ec2.yaml build backend`
antes de volver a crearlo.

### Validar después de aplicar

```bash
curl -i http://127.0.0.1:8000/health/ready
curl -i -H 'Host: api.uctszone.net' http://127.0.0.1:8000/health/ready
curl -i -H 'Host: desconocido.invalid' http://127.0.0.1:8000/health/ready
curl -i -H 'Host: api.uctszone.net' http://127.0.0.1:8000/api/me
curl -i https://api.uctszone.net/health/ready
```

Espera `200` y `{"status":"ok"}` para los hosts permitidos, `400` para el
host desconocido y `401` en `/api/me` sin sesión. Si la prueba con encabezado
`Host` funciona en localhost y la URL pública aún falla, revisa el DNS, el
certificado TLS y el proxy HTTPS del dominio.

### Revertir el cambio

Desde la raíz del proyecto en EC2 y en la misma sesión de despliegue, restaura
la copia y vuelve a crear solo el backend:

```bash
cp -p "$rollback_dir/compose.ec2.yaml" compose.ec2.yaml
docker compose -f compose.beta.yaml -f compose.ec2.yaml \
  up -d --no-deps --no-build --wait backend
curl -fsS http://127.0.0.1:8000/health/ready
```

Si abriste otra sesión SSH, asigna a `rollback_dir` el directorio impreso
al preparar la copia. El restablecimiento conserva los SQLite montados.
