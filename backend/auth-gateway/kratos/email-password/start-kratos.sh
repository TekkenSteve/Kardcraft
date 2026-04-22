#!/bin/sh
set -eu

if [ "${KRATOS_ENV:-dev}" = "prod" ]; then
    exec kratos serve -c /etc/config/kratos/kratos.yml
fi

exec kratos serve -c /etc/config/kratos/kratos.yml -c /etc/config/kratos/kratos.dev.yml --watch-courier
