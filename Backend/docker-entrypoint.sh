#!/bin/sh
set -eu
umask 077

for file in /catalog/ucts_certificados.sqlite /state/ucts_auth.sqlite; do
    if [ ! -r "$file" ] || [ ! -f "$file" ]; then
        echo "La beta requiere un archivo SQLite existente y legible en $file." >&2
        exit 1
    fi
done

if [ ! -w /state ] || [ ! -w /state/ucts_auth.sqlite ]; then
    echo "SQLite requiere escritura en /state y en la base de sesiones. Revisa BETA_UID y BETA_GID." >&2
    exit 1
fi

python -c 'from ucts.cli import main; main()' init-catalog-auth
exec "$@"
