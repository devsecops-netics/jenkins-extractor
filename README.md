# jenkins-extractor

Extrae builds desde la REST API de Jenkins y genera CSV/JSON listos para cuadros de mando. La métrica inicial es la **tasa de éxito**.

## Uso

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export JENKINS_API_URL=https://jenkins.netics.cl/ JENKINS_API_USER=svc-metrics JENKINS_API_TOKEN=xxxx
python -m jenkins_extractor --lookback-days 30 --output out
python -m pytest -q
```

## Salidas (`out/`)

| Archivo | Grano | Uso |
|---|---|---|
| `builds.csv` | 1 fila por build | Tabla de hechos (drill-down, filtros por trigger o nodo) |
| `jobs.csv` | 1 fila por job | Dimensión de jobs (folder, tipo, rama) |
| `success_rate_by_job.csv` | job | Tasa de éxito, conteos por resultado, duración avg/p50/p95, último resultado |
| `success_rate_daily_by_job.csv` | día × job | Tendencia por job |
| `success_rate_daily.csv` | día | Tendencia global |
| `metadata.json` | ejecución | Versión de Jenkins, ventana, errores por job y definición de la métrica |

**Tasa de éxito** = `SUCCESS / (SUCCESS + FAILURE + UNSTABLE)`. Los resultados `ABORTED`, `NOT_BUILT` e `IN_PROGRESS` se cuentan, pero quedan fuera del denominador. Si un grupo no tiene builds en el denominador, el valor queda vacío.

Formato de los archivos: UTF-8 con BOM, separador `,`, decimales con `.`, fechas en ISO‑8601. `started_at_utc` está en UTC y `started_date` en la zona `REPORT_TZ`.

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `JENKINS_API_URL` / `JENKINS_URL` | — | URL raíz de Jenkins. `JENKINS_URL` lo inyecta Jenkins |
| `JENKINS_API_USER` / `JENKINS_API_TOKEN` | — | Usuario de servicio y API token |
| `LOOKBACK_DAYS` | 30 | Ventana de extracción |
| `MAX_BUILDS_PER_JOB` | 500 | Rango `{0,N}` en `allBuilds` |
| `MAX_WORKERS` | 4 | Requests concurrentes contra el controller |
| `JOB_INCLUDE_REGEX` / `JOB_EXCLUDE_REGEX` | — | Filtro sobre `fullName` |
| `REPORT_TZ` | America/Santiago | Zona horaria para agrupar por día |
| `JENKINS_CA_BUNDLE` | — | CA propia (PKI interna) |
| `JENKINS_VERIFY_TLS` | true | Usar `false` solo en laboratorio |
| `EXTRACT_USERS` | false | Incluye el `userId` que disparó el build (PII) |
| `CSV_SANITIZE` | true | Antepone `'` a valores que empiezan con `= + - @` (CSV injection) |

## Ejecución como job en Jenkins

1. Crea un usuario de servicio con permisos **Overall/Read** y **Job/Read** únicamente, y genera su API token.
2. Registra la credencial *Username with password* con id `jenkins-api-extractor`.
3. Crea un job Pipeline from SCM que apunte a este repo; usa el `Jenkinsfile` incluido. Corre diariamente, ejecuta los tests y archiva `out/*.csv` y `metadata.json`.
4. Para consumir el último resultado: `GET $JENKINS_URL/job/<job>/lastSuccessfulBuild/artifact/out/builds.csv`.

Plugins que usa el `Jenkinsfile`: Credentials Binding, Timestamper, JUnit y Workspace Cleanup.

## Notas de diseño

- **Solo lectura:** el extractor hace únicamente llamadas GET, todas con `tree=` para no traer el objeto completo (`depth=N` sobrecarga el controller).
- **Descubrimiento de jobs:** recorre de forma recursiva Folders, Multibranch y Organization Folders. Construye las URLs desde `fullName`, sin confiar en `url`, que depende de la Jenkins URL configurada o del proxy.
- **Reintentos y fallos:** reintenta con backoff ante 429 y 5xx. Si un job falla, se registra en `metadata.errors` y la extracción continúa; con `--strict` termina con exit 1.
- **Extracción completa:** cada corrida regenera la ventana completa, así que es idempotente. Si el volumen crece, el siguiente paso es extraer de forma incremental por `number` por job.
