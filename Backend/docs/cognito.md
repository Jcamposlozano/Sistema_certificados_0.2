# Inicio de sesión con Amazon Cognito y SES

Angular usa `/certificados` y llama a FastAPI bajo el mismo origen. FastAPI abre
`ucts_certificados.sqlite` en solo lectura. La vista `correos_con_principal` debe
identificar exactamente un participante con `principal = 1` para la dirección
solicitada. Solo después de aplicar ese filtro y los límites locales, FastAPI
comprueba la cuenta mediante `AdminGetUser`. Si falta y el participante todavía
no tiene un `sub` vinculado, la crea mediante `AdminCreateUser` sin contraseña y
con `SUPPRESS` para evitar la invitación. Si otra solicitud ya la creó, vuelve
a consultar la cuenta. Una cuenta deshabilitada, pendiente de confirmación o
incompatible con el vínculo existente requiere revisión administrativa.

FastAPI autentica por correo con `USER_AUTH` y `EMAIL_OTP`. Cognito entrega el
código mediante SES. FastAPI calcula `SECRET_HASH`, verifica el código y comprueba
con `GetUser` que el correo esté verificado y que el `sub` coincida con el de la
cuenta comprobada. Angular recibe una cookie de sesión `HttpOnly` y consulta
`/api/me` y `/api/me/certificates`. En cada solicitud protegida la API vuelve a
comprobar la elegibilidad del correo y utiliza el UUID del titular para filtrar
sus asociaciones. El catálogo importado muestra las asociaciones como pendientes.

El ejemplo Flask usa OpenID Connect con redirección. Este portal usa el flujo
`USER_AUTH` de la API de Cognito desde FastAPI. El Cognito User Pool ID del
ejemplo sirve para configurar las llamadas administrativas.

## Configuración del entorno

El pool indicado es `us-east-2_S2qsWPDFm` y el App Client indicado es
`UCTS-Certificados-Backend`. Confirma en la consola que el pool admite el **correo
como atributo de inicio de sesión** (`UsernameAttributes=["email"]`, con
unicidad del correo), requiere únicamente atributos suministrados por el alta,
admite `EMAIL_OTP`, tiene autorregistro deshabilitado y usa SES en `us-east-2`.
El MFA obligatorio es incompatible con este OTP como primer factor. En el App
Client confidencial verifica `ALLOW_USER_AUTH`, `PreventUserExistenceErrors` y
una vigencia del desafío de al menos 3 minutos. Cognito con SES requiere el plan
Essentials o superior para el OTP por correo.
[Flujos de Cognito](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-authentication-flow-methods.html) · [Configuración de SES](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-email.html)

Configura las variables en el entorno del backend. Para el piloto local puedes
usar `Backend/.env`, excluido de Git. Guarda los secretos de producción en el
gestor de secretos del despliegue.

```dotenv
APP_ENV=local
AUTH_MODE=cognito
AWS_REGION=us-east-2
COGNITO_USER_POOL_ID=us-east-2_S2qsWPDFm
COGNITO_CLIENT_ID=7v03sfiuv9d9nk1va6t27hkmcf
COGNITO_CLIENT_SECRET=<secreto del App Client>
OTP_SECRET=<clave aleatoria de al menos 32 caracteres>
CERTIFICATE_CATALOG_SQLITE=data/ucts_certificados.sqlite
DATABASE_URL=sqlite:///data/ucts_auth.sqlite
COOKIE_SECURE=false
ALLOWED_ORIGINS=["http://localhost:4200"]
ALLOWED_HOSTS=["localhost","127.0.0.1"]
OTP_TTL_SECONDS=180
OTP_RESEND_SECONDS=60
SESSION_TTL_SECONDS=3600
```

Genera `OTP_SECRET` con `.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'`.
Conserva el `DATABASE_URL` actual si ya existe una base compatible para sesiones.
El ejemplo SQLite usa un archivo privado separado del catálogo. Mantén las
credenciales AWS fuera del `.env` y del código. Usa `AWS_PROFILE` localmente y
un rol IAM en producción. Las únicas acciones administrativas requeridas por
el proceso son las siguientes, sobre el ARN del pool.

```json
{
  "Effect": "Allow",
  "Action": [
    "cognito-idp:AdminGetUser",
    "cognito-idp:AdminCreateUser"
  ],
  "Resource": "arn:aws:cognito-idp:us-east-2:<id-cuenta>:userpool/us-east-2_S2qsWPDFm"
}
```

El App Client autoriza `InitiateAuth`, `RespondToAuthChallenge` y `GetUser`.
Cognito es quien llama a SES. El rol de FastAPI no requiere `ses:SendEmail`.
La revisión de configuración en AWS se puede realizar con otro rol que tenga
`DescribeUserPool`, `DescribeUserPoolClient` y los permisos de lectura de SES.
[Modelos de autorización](https://docs.aws.amazon.com/cognito/latest/developerguide/authentication-flows-public-server-side.html) · [Alta sin contraseña](https://docs.aws.amazon.com/cognito/latest/developerguide/how-to-create-user-accounts.html)

## Piloto con un solo participante

Desde `Backend`, si usas el archivo SQLite de sesiones, inicialízalo con
`umask 077` y `.venv/bin/ucts init-catalog-auth`. El comando se puede repetir.
Arranca FastAPI con el perfil autorizado.

```bash
AWS_PROFILE=<perfil-autorizado> .venv/bin/uvicorn ucts.main:create_app --factory --host 127.0.0.1 --port 8000
```

Opcionalmente, comprueba o da de alta de forma anticipada la cuenta del
participante del piloto. El comando solicita el correo interactivamente, consulta
el catálogo y la vinculación existente y suprime la invitación.

```bash
AWS_PROFILE=<perfil-autorizado> .venv/bin/ucts provision-cognito-user
```

Desde `Fronted/ucts-zone`, ejecuta `npm ci` y `npm start`. Abre
`http://localhost:4200/certificados`. Con el consentimiento del titular o usando
un buzón de prueba controlado y autorizado, solicita un solo código. El titular
lo introduce directamente en el portal. Comprueba recepción, acceso, recarga,
certificados propios y cierre de sesión. Para registrar la evidencia, anota
fecha, entorno y resultado de cada paso, omitiendo correo, código y cookies.

Si cambia el correo principal, la API bloquea el acceso con el correo anterior
y rechaza un nuevo `sub` para ese participante. Un administrador debe actualizar
el atributo email de la misma cuenta de Cognito antes del siguiente acceso.
Si el cambio afecta el inicio de sesión, verifica en Cognito el atributo efectivo
antes de solicitar el código.

## Despliegue autorizado

1. Publica FastAPI con `APP_ENV=production`, `COOKIE_SECURE=true`,
   `ALLOWED_ORIGINS=["https://uctszone.net"]` y los hosts que realmente recibe
   FastAPI en `ALLOWED_HOSTS`. Monta el catálogo en solo lectura y conserva
   almacenamiento persistente para sesiones. Si usas SQLite para sesiones,
   apunta todas las solicitudes del piloto a una única instancia con volumen
   persistente. Configura el rol IAM y verifica `/health/ready`.
2. Verifica que DNS y el certificado de CloudFront cubran `uctszone.net`. Para
   un certificado ACM de CloudFront, emítelo o impórtalo en `us-east-1`, aunque
   Cognito y SES estén en `us-east-2`.
3. Configura el comportamiento `/api/*` hacia el origen HTTPS de FastAPI con
   caché deshabilitada. Permite los métodos necesarios, incluidos POST y OPTIONS,
   y reenvía la cookie `ucts_session`, `Origin` y las cabeceras requeridas por
   la API. Conserva `Set-Cookie` hacia el navegador. Evita registrar cookies o
   cuerpos de solicitudes. Aplica el comportamiento del frontend a las rutas
   Angular. Después del cambio, `GET /api/me` sin cookie debe responder HTTP 401
   desde FastAPI.
4. Ejecuta la prueba de un solo participante en `https://uctszone.net/certificados`.

[Políticas de solicitudes de origen en CloudFront](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-origin-request-policies.html) · [Certificados para dominios personalizados](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cnames-and-https-requirements.html)

## Verificar el desafío y la entrega

Arranca FastAPI con `ucts.main:create_app`. El comando `piloto:create_pilot`
simula AWS y no envía correo. Cuando Cognito devuelve el desafío, la consola de
Uvicorn muestra `Cognito devolvió EMAIL_OTP (AWS RequestId=...)`. Ese identificador
corresponde a la llamada de Cognito. El `200` del endpoint público es genérico y
el identificador de Cognito no confirma entrega del mensaje.

Para seguir el mensaje en AWS, asocia al User Pool un **Configuration set** de
SES en `us-east-2` con un destino de eventos para **Send**, **Delivery** y
**Bounce**. Ejecuta una sola prueba y revisa la ventana horaria del intento.
`Send` confirma que SES aceptó el envío, `Delivery` que el servidor de correo
destino aceptó el mensaje y `Bounce` que lo rechazó. Confirma la recepción final
en el buzón, incluida la carpeta de correo no deseado.

[Configuración de correo del User Pool](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-email.html) · [Publicación de eventos de SES](https://docs.aws.amazon.com/ses/latest/dg/monitor-using-event-publishing.html)

## Diagnóstico

| Señal | Qué comprobar |
| --- | --- |
| Respuesta genérica y no llega el código | Correo principal único, logs de operación de FastAPI, cuenta habilitada, App Client, remitente y región en el User Pool. |
| `AccessDeniedException` | Perfil o rol efectivo, recurso de la política y los dos permisos administrativos. |
| `NotAuthorizedException` | Client ID, Client Secret, habilitación del usuario y flujo `ALLOW_USER_AUTH`. |
| Error de entrega | Identidad remitente verificada, estado de envío de SES, sandbox, lista de supresión y cuota. |
| 429 | Respeta `Retry-After`. La API limita solicitudes por IP y correo. |
| 401 al verificar | Usa el código más reciente. El desafío caduca y admite hasta cinco intentos. |
| 401 tras un OTP válido | Verifica `Set-Cookie`, el reenvío de la cookie, HTTPS y la base persistente de sesiones. |
| 403 XML desde CloudFront | Comprueba que `/api/*` apunte al origen FastAPI y que los POST estén habilitados. |

Mantén deshabilitada la depuración de boto3 y botocore en producción. Los avisos
del adaptador incluyen códigos o tipos de error. ¿No llega el código? Consulta
esos avisos, además de Cognito y SES, sin divulgar información de la cuenta.

Para pruebas automatizadas, en `Backend` ejecuta `.venv/bin/python -m pytest -q`.
En `Fronted/ucts-zone` ejecuta `npm test -- --watch=false` y `npm run build`.
