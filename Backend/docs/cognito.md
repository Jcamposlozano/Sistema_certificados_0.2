# Conector Amazon Cognito

El adaptador usa boto3. La API inicia USER_AUTH con PREFERRED_CHALLENGE=EMAIL_OTP, responde al desafío con EMAIL_OTP_CODE y valida el token resultante contra get_user. No requiere crear un OTP propio con Lambda.

## Configuración requerida en AWS

1. User pool en plan Essentials o Plus, con email como atributo de acceso y EMAIL_OTP entre los primeros factores permitidos.
2. Entrega de email configurada con Amazon SES, identidad remitente verificada y región compatible. Si SES está en sandbox, sus destinatarios también necesitan verificación; solicitar salida del sandbox para envío general.
3. App client con `ALLOW_USER_AUTH`. Activa `PreventUserExistenceErrors` y ajusta la duración de sesión del desafío a **3 minutos** o más (la API limita su validez local a 180 s).
4. El usuario debe existir en el user pool y estar habilitado para este flujo. Este backend no registra usuarios ni crea recursos AWS. Definir aprovisionamiento de usuarios al incorporar inscripciones es una tarea posterior.
5. Configura MFA de forma compatible con el acceso sin contraseña. Comprueba las restricciones actuales del user pool antes de habilitarlo.

Variables en `.env` (no en Angular):

```dotenv
AUTH_MODE=cognito
AWS_REGION=us-east-1
COGNITO_CLIENT_ID=...
COGNITO_CLIENT_SECRET=...
```

`COGNITO_CLIENT_SECRET` es opcional: si existe, el conector calcula SECRET_HASH en cada desafío. No confundir el client ID con el user pool ID. Estas operaciones de login usan el app client, no requieren permisos IAM administrativos; el cliente usa solicitudes sin firma IAM para estas operaciones públicas de autenticación. La región se toma de AWS_REGION. No introducir llaves AWS en el código ni en el navegador.

## Sesión de la plataforma

El `AccessToken` de Cognito se valida en Cognito y no se persiste ni se devuelve al navegador. La API crea una sesión opaca en PostgreSQL y devuelve una cookie HttpOnly. La respuesta get_user debe incluir `sub`, email y email_verified=true. La identidad se asocia al participante importado únicamente por correo verificado; luego se comprueba el `sub` para evitar reasociaciones silenciosas.

La cookie expira a la hora (configurable). No hay refresh tokens. Logout revoca la sesión local. Revocaciones en Cognito después del login no se propagan automáticamente; se necesitará una política de revocación adicional si se requiere ese comportamiento.

Un correo desconocido recibe la misma estructura de respuesta de solicitud; la verificación posterior falla con un error genérico. Los errores operativos de Cognito se traducen a 503 y los límites a 429 sin exponer mensajes internos.

## Validación real pendiente

Las pruebas incluidas verifican las llamadas AWS con Stubber, sin consumir el servicio real. Para una prueba real se necesita el app client configurado y una cuenta de prueba que pueda recibir correos SES. No se han creado recursos ni se han enviado correos en tu cuenta AWS.

Referencias:

- https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_InitiateAuth.html
- https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_RespondToAuthChallenge.html
- https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-email.html
- https://docs.aws.amazon.com/cognito/latest/developerguide/authentication.html
