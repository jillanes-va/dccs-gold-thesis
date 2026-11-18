# Evaluación de `pilot.py` centrada en Reuters

Fecha: 2026-10-21. Prueba de ingeniería; no es evidencia científica sobre mercados ni una medición de cobertura de Reuters.

**Resultado:** el piloto termina y genera sus tres archivos, pero no recupera artículos reales de Reuters. Se identificaron dos causas diferentes: un problema de confianza de certificados en el equipo y, una vez resuelto en el proceso de prueba, reglas de `robots.txt` que deniegan las dos semillas al agente del piloto. La extracción real de Reuters queda sin verificar.

## Alcance y entorno

- Código evaluado: `src/pilot.py`, sin modificaciones.
- Referencia Git: `ede942f864818f8cb0e5dc062bcd8085e667e9f3`; había cambios locales ajenos a la prueba.
- SHA-256 del piloto: `b9ffb17b2e51033dac4966e6da47b2887f58111763fed65f2b5ad3860b2f4e39`.
- Windows; Python 3.11.15; requests 2.34.2; trafilatura 2.3.1; Beautiful Soup 4.15.0; python-dateutil 2.9.0.post0.
- Solo Reuters; máximo de **60 candidatos**, intervalo configurado de 3 segundos, timeout de 20 segundos y mínimo de 100 palabras. El máximo cuenta intentos de candidatos, no artículos exitosos.
- Se mantuvo el período del código: **2026-01-01 a 2026-10-15 inclusive**. Las noticias del día de ejecución, 2026-10-21, quedarían fuera.
- No se cambiaron hipótesis, reglas científicas, agente HTTP ni configuración persistente de certificados. No se agregaron dependencias.
- Las evidencias nuevas se guardaron en `data/diagnostics/`, ya ignorado por Git. Los archivos originales de `output/` se conservaron.

## Ejecuciones reales

| Ejecución | Resultado de la solicitud a robots | Decisiones sobre semillas | Solicitudes a páginas de semillas | Solicitudes a artículos | Artículos recuperados |
|---|---|---|---:|---:|---:|
| Confianza TLS predeterminada de requests | `SSLError`, sin respuesta HTTP | 2 negativas por robots no disponible | 0 | 0 | 0 |
| Confianza TLS del sistema Windows | HTTP 200; archivo de reglas válido | 2 negativas por reglas explícitas | 0 | 0 | 0 |

En total se hicieron **dos solicitudes HTTP intentadas**, ambas a `https://www.reuters.com/robots.txt`, una por ejecución. Una falló en TLS y otra obtuvo HTTP 200. Las dos semillas son decisiones lógicas, **no dos solicitudes remotas**: el resultado de robots se almacena en caché por origen.

### 1. Certificados del equipo institucional

La primera ejecución registró `SSLCertVerificationError` con el detalle `self-signed certificate in certificate chain`. Esto demuestra un fallo de validación de confianza TLS; no permite concluir que el parser o el descubrimiento de artículos fallen. No se estableció qué componente institucional introduce la cadena de certificados ni se necesitaron credenciales nuevas.

La segunda ejecución usó `truststore.inject_into_ssl()` **solo dentro del proceso de auditoría**, con la biblioteca ya instalada. Al utilizar los certificados del sistema, la consulta obtuvo HTTP 200 manteniendo la verificación HTTPS activa. Esto es compatible con la configuración institucional indicada por el investigador; no prueba una causa específica como un proxy determinado.

### 2. Reglas de Reuters

La respuesta de robots recibida incluye un grupo genérico con estas reglas:

```text
User-agent: *
Allow: /plus/
Disallow: /
```

El agente real del piloto, `AcademicNewsPilot/0.1`, cae en ese grupo. `RobotFileParser` devolvió `False` para `/business/` y `/markets/`. La excepción `/plus/` no corresponde a las semillas de este piloto. El aviso del archivo también remite a consentimiento previo para la recopilación automatizada.

Fuente primaria consultada: [robots.txt de Reuters](https://www.reuters.com/robots.txt). La [copia recibida](../data/diagnostics/reuters_20261021T195209007651Z/robots_response_1.txt) permite auditar qué se observó en esta fecha; las reglas pueden cambiar.

No se observaron HTTP 401, 403 o 429 de páginas de noticias: **esas páginas no se solicitaron**. Tampoco se observaron errores reales de extracción. No se ensayaron rutas para eludir esta restricción.

## ¿Es el output esperado?

Sí, para las ramas de control que se ejecutaron: ambas corridas terminan con dos filas en `attempts.csv`, un `articles.jsonl` vacío y el siguiente `summary.json`:

```json
{
  "reuters": {
    "discovery_robots_disallowed_or_unavailable": 2
  }
}
```

Pero ese output **es insuficiente para diagnosticar la causa**: representa igual un fallo TLS y una prohibición explícita. El `http_status` vacío en las filas de semillas no demuestra un bloqueo HTTP: las semillas nunca se solicitaron y el esquema no tiene un campo independiente para el estado HTTP de robots. El wrapper de auditoría conserva esos detalles en archivos separados.

El código devuelve éxito de proceso incluso cuando no recupera noticias; un exit code 0 solo indica que completó la rutina. La salida histórica en `output/` presenta el mismo estado genérico, pero sin sus detalles de red no puede atribuirse retrospectivamente a una causa específica.

## Pruebas locales sin internet

Se ejecutaron **86 pruebas: 79 pasaron y 7 reprodujeron defectos pendientes** mediante `expectedFailure`. No hubo errores inesperados, fallos inesperados ni pruebas omitidas. El resultado `OK (expected failures=7)` no significa que esos siete defectos estén corregidos.

La batería bloquea las solicitudes de red no simuladas y utiliza HTML sintético, sin reproducir noticias de Reuters. Incluye fechas y límites temporales, normalización y deduplicación de URLs, metadatos JSON-LD, extracción con trafilatura, robots, errores HTTP y de transporte, pausas, redirecciones y escritura de resultados.

Se comprobó un recorrido completo con HTTP simulado y extracción real del HTML sintético. Otro escenario procesó **60 candidatos únicos**, repartidos entre dos semillas con enlaces repetidos. Produjo 62 filas de auditoría —2 de descubrimiento y 60 de candidatos— y esta distribución:

| Resultado | Filas |
|---|---:|
| `discovery_ok` | 2 |
| `blocked_or_rate_limited` | 12 |
| `request_error:Timeout` | 6 |
| `http_error` | 6 |
| `outside_period` | 6 |
| `short_or_empty` | 6 |
| `success` | 6 |
| `extraction_error` | 6 |
| `not_html` | 6 |
| `missing_date` | 6 |

Se verificaron los seis registros JSONL exitosos, sus hashes SHA-256, la ausencia de solicitudes duplicadas, el límite de intentos y la consistencia entre CSV y resumen. Los errores de extracción y las ausencias de fecha de ese escenario fueron inyectados deliberadamente. **Estas cifras son simulaciones; no son tasas de recuperación de Reuters.**

### Defectos reproducidos

| Prioridad técnica | Hallazgo | Consecuencia |
|---|---|---|
| Alta | La regla del destino de una redirección se verifica después de que requests lo descarga. | Se descarta el cuerpo, pero la solicitud al destino ya ocurrió. Debe verificarse cada salto antes de seguirlo. Reproducido exclusivamente con transporte simulado. |
| Alta | Un HTTP 200 con HTML de login/challenge se acepta como si fuera robots. | El parser puede permitir el acceso sin haber recibido reglas válidas. |
| Media | TLS, indisponibilidad de robots y prohibición explícita comparten resultado. | El output oculta la etapa y causa real del fallo. |
| Media | La petición de robots no participa en el control de pausas. | La primera página puede solicitarse inmediatamente después de robots, aunque se configure un intervalo. |
| Media | Los patrones de descubrimiento incluyen páginas de sección. | Consumen el cupo de candidatos y no garantizan descubrir artículos. |
| Media | HTTP 401, 403 y 429 comparten resultado. | Autenticación, denegación y límite de tasa no quedan separados en la clasificación, aunque el código HTTP sí se conserva para páginas. |
| Media | Las filas originales no registran timestamp de recuperación. | No permiten reconstruir por sí solas cuándo se intentó cada acceso. |

Otros límites observados en el código: las semillas son secciones actuales, sin recorrido histórico; los fallos de robots quedan en caché durante toda la ejecución; no se implementan reintentos con backoff ni checkpoints. Son límites de diseño observados, no resultados de una evaluación de cobertura histórica.

## Reproducción y evidencias

```powershell
# Pruebas locales; no habilita red. Genera informe y trazas en una carpeta nueva.
uv run --offline --no-sync python scripts/audit_reuters.py --offline-tests

# Alternativa estándar para ejecutar la batería local.
uv run --offline --no-sync python -m unittest discover -s tests -v

# Prueba remota acotada; --offline aquí solo impide descargar dependencias con uv.
# El argumento --live habilita expresamente las solicitudes del script.
uv run --offline --no-sync python scripts/audit_reuters.py --live --max-per-source 60 --delay 3 --timeout 20

# Variante para el almacén institucional de certificados, con TLS verificado.
uv run --offline --no-sync python scripts/audit_reuters.py --live --system-trust --max-per-source 60 --delay 3 --timeout 20
```

- [Primera ejecución: manifiesto](../data/diagnostics/reuters_20261021T195039816697Z/manifest.json) y [error TLS](../data/diagnostics/reuters_20261021T195039816697Z/http.jsonl).
- [Segunda ejecución: manifiesto](../data/diagnostics/reuters_20261021T195209007651Z/manifest.json), [HTTP](../data/diagnostics/reuters_20261021T195209007651Z/http.jsonl), [decisiones de robots](../data/diagnostics/reuters_20261021T195209007651Z/robots_decisions.jsonl) y [CSV del piloto](../data/diagnostics/reuters_20261021T195209007651Z/pilot/attempts.csv).
- [Resultados locales finales y trazas de defectos](../data/diagnostics/reuters_20261021T195631672844Z/offline_results.json) y [log de las 86 pruebas](../data/diagnostics/reuters_20261021T195631672844Z/offline_tests.txt). Este informe final corresponde al hash de tests `456c610907b0092c697187770620e4f207af367b485e87539adf1c177d700e29`; sustituye la corrida local preliminar conservada en otra carpeta.

Archivos nuevos para revisión: `scripts/audit_reuters.py`, `tests/test_pilot_reuters.py` y este informe. No se modificó `pilot.py`, no se sobrescribió `output/` y no se hicieron commits ni operaciones remotas de Git.

El siguiente trabajo técnico sería corregir los defectos reproducidos y agregar diagnóstico de confianza TLS. Recuperar un corpus real de Reuters requiere una vía de acceso autorizada por la fuente; elevar `--max-per-source` no resolverá la barrera observada. La cobertura histórica y la calidad de extracción de artículos reales siguen pendientes.
