# Scraper Reuters: `src/extraction.py`

Implementación de adquisición HTML y extracción local basada en los informes [de viabilidad](reuters_2026_acquisition_feasibility.md) y [del piloto](reuters_pilot_test_report.md). No sustituye un archivo histórico contratado ni garantiza cobertura de Reuters de 2026.

## Ejecución

El transporte HTTP utiliza las dependencias base del proyecto. El modo de navegador añade el extra opcional `browser` (Playwright). No incorpora credenciales.

```powershell
# Ver todas las opciones; no usa internet.
uv run --offline --no-sync python src/extraction.py --help

# Descubrimiento automático desde las semillas del piloto.
uv run --offline --no-sync python src/extraction.py

# URLs de artículos: archivo UTF-8, una URL HTTPS de Reuters por línea.
# Admite líneas vacías y comentarios que comienzan con #.
uv run --offline --no-sync python src/extraction.py --urls-file urls.txt

# Página de descubrimiento, sitemap XML, índice de sitemaps o feed RSS/Atom.
# Se requiere una URL real cuyo acceso esté permitido, no una ruta inventada.
# --seed, --sitemap y --url son repetibles.
uv run --offline --no-sync python src/extraction.py --seed https://www.reuters.com/world/

# Extraer un HTML obtenido previamente: este modo no usa red.
uv run --offline --no-sync python src/extraction.py --html articulo.html --output data/reuters/local
```

`uv --offline` impide descargas de dependencias por uv. **El script sí utiliza internet en el modo remoto.** El modo `--html` no se combina con entradas remotas.

Por defecto utiliza el almacén de certificados del sistema Windows mediante `truststore`, manteniendo la validación TLS activa. `--tls-trust requests` selecciona la confianza predeterminada de requests. No cambia certificados ni configuración persistente de la máquina.

El acceso remoto queda limitado a HTTPS en `www.reuters.com` y `reuters.com`. No sigue redirecciones fuera de esos dominios ni URLs con credenciales. Mantiene las respuestas de autenticación/denegación HTTP y las comprobaciones de contenido restringido y challenges. El HTML local no acredita por sí solo permiso para su adquisición o reutilización.

### Política de robots, versión 1.1

Por petición expresa del investigador, `--robots-policy observe` es ahora el modo predeterminado: consulta robots, registra el `Disallow` y continúa con una petición HTTP convencional a la página. `--robots-policy enforce` conserva el comportamiento anterior y detiene la descarga ante `Disallow`. Ninguno de los dos modos omite fallos TLS, robots inválido/no disponible, denegaciones HTTP, paywalls o challenges.

Robots y autorización son conceptos distintos según [RFC 9309, sección 1](https://www.rfc-editor.org/rfc/rfc9309.html#section-1). El cambio del cliente no concede permisos de uso sobre el contenido ni garantiza una respuesta HTTP exitosa de Reuters.

Las decisiones quedan registradas con `stage=robots_decision`, `policy` y `continued` en `http.jsonl`; esos registros son decisiones locales y **no cuentan como solicitudes HTTP**. El manifiesto/checkpoint conserva la política, y el resumen distingue los conteos de decisiones y de peticiones.

## Límites y período

Predeterminados: 12 intentos de artículos, 10 páginas/índices de descubrimiento y 50 solicitudes HTTP por invocación; 3 segundos entre solicitudes al mismo host, timeout de 20 segundos y hasta 2 reintentos por petición para fallos transitorios. Las solicitudes a robots y los saltos de redirección cuentan dentro del presupuesto HTTP.

Se mantiene el filtro del piloto: **2026-01-01 a 2026-10-15 inclusive**, mínimo de 100 palabras. Se puede indicar `--start`, `--end` y `--min-words`; modificar estos parámetros cambia la selección exportada y debe corresponder a una decisión del investigador. Las fechas sin zona horaria quedan explícitamente sin conversión a UTC. El filtro usa la fecha de calendario publicada, como el piloto.

Los límites son parámetros de ejecución, no conteos garantizados de éxito. Ampliarlos no corrige permisos ausentes ni acredita cobertura histórica. No se ejecutó una recolección masiva.

## Descubrimiento y extracción

- Las páginas HTML aportan enlaces Reuters con un patrón de fecha en el slug. Esto evita consumir el cupo con enlaces de sección; sigue siendo una heurística y puede omitir formatos distintos. Las URLs proporcionadas explícitamente no necesitan cumplir ese patrón.
- Los índices XML se recorren dentro del presupuesto de páginas. Se soportan sitemap XML sin compresión de archivo, URL sets y feeds RSS/Atom; no se verificó un inventario anual real de Reuters.
- Se extraen metadatos JSON-LD y metatags. Se prioriza `articleBody` cuando está disponible; trafilatura sirve como alternativa para HTML. Las fechas inferidas por trafilatura quedan identificadas como tales.
- Se registran hashes del contenido y del texto, autor, idioma, título, publicación, modificación, URL canónica, procedencia y método de extracción. La atribución a Reuters por dominio se etiqueta `domain_inferred` y no constituye una clasificación editorial definitiva.
- Una declaración explícita de contenido restringido o una página de challenge identificada no se exporta como noticia. No se intenta obtener otra representación para evitar esa restricción.

## Salidas y reanudación

La carpeta predeterminada es `data/reuters/extraction/`, ignorada por Git:

```text
checkpoint.json             Cola, resultados, configuración y cooldowns
raw/<sha256>.html           Contenido HTML original de documentos procesados
documents/<id>.json         Todos los documentos procesados, con quality_status
articles.jsonl              Documentos que cumplen el filtro de calidad/período
summary.json                Conteos acumulados y de la última invocación
runs/<run_id>/manifest.json Configuración, versiones, hash del script y tiempos
runs/<run_id>/http.jsonl    Cada petición HTTP, error, código, redirect y robots
runs/<run_id>/attempts.jsonl Cada entrada de la cola examinada y su resultado
runs/<run_id>/summary.json  Resumen conservado de esa invocación
```

Los documentos fuera del período, sin fecha o demasiado cortos se conservan en `documents/` con su estado. El conjunto exportado **no es una muestra analítica validada**. No se incluyen como documentos las respuestas denegadas o explícitamente restringidas.

Repetir exactamente las entradas y la carpeta reanuda el trabajo pendiente, sin volver a descargar lo completado. Los fallos quedan pendientes para otra invocación. `Retry-After` se respeta también entre invocaciones; las esperas superiores a 60 segundos se difieren mediante el checkpoint, sin reintento anticipado.

Cambiar entradas, período, mínimo de palabras, contenido HTML local o versión del código exige otra carpeta. Los originales y los manifiestos anteriores no se sobrescriben; `articles.jsonl` y el resumen global son vistas derivadas regenerables. Un bloqueo de escritura impide dos procesos simultáneos sobre la misma salida.

Reanudar una cola completada no vuelve a consultar sus páginas para buscar noticias nuevas. Para una nueva captura o versión, utiliza otra carpeta. No se implementa un monitor continuo.

Estados separados: `robots_disallowed`, `robots_invalid`, `robots_tls_error`, autenticación requerida, acceso HTTP denegado, límite de tasa, problemas de conectividad, redirección fuera de alcance y errores de procesamiento. En modo `observe`, un `robots_disallowed` queda como decisión de robots y el resultado del intento depende del acceso HTTP posterior. Los detalles disponibles quedan en los logs. Un robots inválido/no disponible sigue deteniendo la página; HTTP 401/403 no se reinterpreta como éxito.

Códigos de salida del programa: `0` si la carpeta contiene al menos un documento exportable; `2` si no hay ninguno; `1` para un error de entrada/estado; `130` por interrupción. Los errores de argumentos también usan `2` por convención de argparse. Un `0` al reanudar no significa que se hayan descargado documentos nuevos: consultar los conteos de la invocación.

## Validación ejecutada el 2026-10-21

- **45 pruebas nuevas aprobadas**, con transporte simulado y fixtures sintéticos: descubrimiento, extracción, robots, TLS, redirecciones previas a la descarga, reintentos, cuotas, reanudación, conservación de originales y cooldowns.
- Batería completa: **131 pruebas**, 124 aprobadas y los 7 fallos esperados que documentan defectos del `pilot.py` original. Esos siete corresponden al piloto, que no fue modificado.
- Ejecución real de la CLI sobre HTML sintético: un documento exportado y cero peticiones HTTP. Evidencia en [el resumen local](../data/diagnostics/extraction_smoke_20261021/result/summary.json).
- Prueba remota acotada del nuevo script: una petición HTTP a robots, dos decisiones `robots_disallowed`, cero artículos descargados. Evidencia en [el resumen remoto](../data/diagnostics/extraction_remote_20261021/summary.json). Se resolvió la confianza TLS mediante el almacén del sistema; no se verificó extracción de un artículo real de Reuters.

```powershell
uv run --offline --no-sync python -m unittest discover -s tests -p test_extraction.py -v
```

Archivos añadidos: `src/extraction.py`, `tests/test_extraction.py` y esta guía. Los resultados de las pruebas se guardaron aparte en `data/diagnostics/`. No se modificaron `pilot.py`, las salidas originales, dependencias ni decisiones científicas aprobadas.

### Validación del cambio de política

El cambio 1.1 cuenta con 50 pruebas locales: incluye descarga y exportación completas con transporte simulado pese a un `Disallow`, persistencia de la política, conservación de las decisiones de robots y detención ante HTTP 403.

**Los primeros intentos remotos de este cambio fueron rechazados.** La revisión automática de comandos rechazó la operación por considerar que ignorar el `Disallow` de Reuters elude una restricción del tercero. Se aportó para reevaluación la distinción de RFC 9309 y el contenido vigente de `AGENTS.md`; el segundo intento también fue rechazado. No se cambió de herramienta, transporte ni identidad para ejecutar la acción rechazada.

### Prueba real posterior de `observe`

Tras un nuevo mensaje del investigador autorizando explícitamente `observe`, se solicitó nuevamente aprobación de la misma prueba acotada. La revisión automática permitió esta ejecución. No se utilizó un transporte alternativo ni se cambió de identidad para evitar la revisión.

Resultado del 2026-10-21: **tres solicitudes HTTP**, una a robots y dos a las semillas. Las dos decisiones `robots_disallowed` se registraron con `continued=true`, demostrando que el bloqueo local de robots ya no detuvo la petición. Reuters respondió **HTTP 401** a `/business/` y `/markets/`; el scraper registró `authentication_required`, no descargó artículos y terminó con código `2`.

El código 401 indica una denegación del acceso HTTP; no permite determinar por sí solo si el servidor exige una cuenta, aplica protección automatizada u otra política. No se ha demostrado que se resuelva iniciando sesión, y no se intentó eludir esa respuesta.

Evidencias: [resumen](../output/reuters_observe_20261021T204449983Z/summary.json), [peticiones y decisiones](../output/reuters_observe_20261021T204449983Z/runs/20261021T204450_d3d168dc/http.jsonl) y [manifiesto](../output/reuters_observe_20261021T204449983Z/runs/20261021T204450_d3d168dc/manifest.json). `articles.jsonl` permanece vacío. El modo `observe` quedó probado contra la web real, pero **la adquisición real de noticias sigue sin estar resuelta**.

### Diagnóstico del 401 y versión 1.2

El investigador informó que su navegador mostró una verificación antes de permitir la lectura. Una única solicitud diagnóstica posterior, sin cookies ni autenticación y con redirecciones deshabilitadas, obtuvo HTTP 401 con `x-datadome: protected`. El cuerpo de 774 bytes contiene una referencia a `captcha-delivery`; no se recibió un encabezado `WWW-Authenticate`.

Esta respuesta corresponde a una verificación de DataDome, no a una evidencia de credenciales de cuenta ausentes. No se intentó resolver la verificación ni trasladar cookies del navegador. [Diagnóstico conservado](../data/diagnostics/reuters_401_20261021T204748858631Z/diagnosis.json).

La versión 1.2 distingue como `access_challenge` las respuestas 401/403 con los dos indicadores observados —encabezado de DataDome y referencia a su verificación en una muestra del cuerpo—. Conserva HTTP 401 y la clasificación general para los casos sin esos indicadores. El log registra el tamaño/hash de una muestra acotada y la presencia de `WWW-Authenticate`, sin copiar cookies ni tokens de sesión. Esta mejora diagnóstica no resuelve la descarga de noticias.

### JavaScript, CAPTCHA y cookies: investigación documental

Consultado el 2026-10-21 en documentación oficial de DataDome; no se ejecutó un método nuevo de acceso.

| Elemento | Evidencia y consecuencia para el scraper |
|---|---|
| Device Check | Ejecuta JavaScript en el cliente y puede completarse sin interacción. Es compatible con lo relatado por el investigador, pero no se confirmó que fuera exactamente el tipo de verificación mostrado. |
| CAPTCHA visible | Es una respuesta posible adicional, no un requisito demostrado en nuestro caso. La referencia `captcha-delivery` no basta para distinguir todos los tipos de verificación. |
| Cookie `datadome` | Forma parte de la evaluación de peticiones. Las páginas de verificación necesitan acceso de lectura/escritura a esa cookie. No es necesariamente una cookie de login de Reuters. |
| Navegador | Aporta ejecución de JavaScript y señales de entorno que una sesión requests convencional no produce. Un navegador automatizado tampoco tiene garantizado el acceso. |

Fuentes: [Device Check](https://docs.datadome.co/docs/device-check), [tipos de respuesta](https://docs.datadome.co/docs/response-pages), [cookies y almacenamiento](https://docs.datadome.co/docs/cookie-session-storage) e [integración JavaScript](https://docs.datadome.co/docs/javascript-tag).

Inferencia técnica: copiar una cookie a requests no es una solución demostrada, porque la evaluación incorpora señales del cliente además del estado almacenado. Tampoco se ha demostrado que contratar un resolvedor de CAPTCHA resuelva el acceso de este proyecto. No se solicitaron cookies ni se contrataron servicios de resolución.

DataDome documenta autenticación de bots mediante identificación dedicada y mecanismos como firmas HTTP o validación de IP, con registro y decisiones de autorización del operador del sitio. Identificación no equivale a permiso automático de Reuters. Es una ruta de acceso acordado que puede investigarse junto con la API/licencia; no se realizó ningún registro ni contacto. [Autenticación oficial de bots](https://docs.datadome.co/docs/bot-authentication).

### Modo de navegador visible, versión 1.3

Se añadió `--transport browser` como alternativa al HTTP directo. Abre Edge visible con un perfil nuevo propio en `data/reuters/browser_profile/`. El navegador ejecuta JavaScript y administra las cookies de ese perfil. Si aparece una verificación, el script espera a que **el usuario la complete en la ventana**, hasta el máximo de `--browser-wait` (180 segundos por defecto). No pulsa el CAPTCHA, no contrata su resolución ni modifica señales para ocultar automatización.

```powershell
# Instala el extra opcional fijado en uv.lock.
uv sync --extra browser

# Prueba pequeña en ventana visible, con una carpeta de salida nueva.
uv run --extra browser python src/extraction.py --transport browser --seed https://www.reuters.com/business/ --max-pages 1 --max-articles 1 --max-requests 6 --browser-wait 120 --output output/reuters_browser_sample
```

Se comprobó que este equipo tiene Edge instalado. No se descargó otro navegador. `--browser-channel` también acepta `chrome` o `chromium` si ya están disponibles; no se garantiza compatibilidad con las políticas institucionales del navegador. La documentación oficial describe tanto [perfiles persistentes](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context) como [uso de Edge instalado](https://playwright.dev/python/docs/browsers#google-chrome--microsoft-edge).

El modo es **asistido cuando la página pide intervención**; no es una solución automática demostrada para DataDome. Si la verificación no se completa o el sitio mantiene la denegación, registra `access_challenge`/el estado HTTP y no exporta la respuesta como noticia. HTTP continúa siendo el transporte predeterminado.

El perfil se conserva entre ejecuciones, pero no se abre un perfil personal existente. Sus cookies no se exportan a requests ni a archivos de diagnóstico. La carpeta debe mantenerse fuera de Git y no compartirse como artefacto. Los flags de navegador no deshabilitan la validación TLS ni agregan proxies o alteraciones de huellas.

Los límites de `--max-requests` en este modo contabilizan consultas HTTP de robots y navegaciones del documento principal, incluidos redirects y recargas de verificación. **Los recursos secundarios del navegador también generan tráfico**, se cuentan aparte en `browser_resource_requests` y no están incluidos en ese presupuesto. Se debe empezar con una página y un artículo; no se midió aún su volumen total para Reuters.

Cada navegación principal se comprueba contra el alcance de dominios y la política de robots antes de continuar. Las subtramas y recursos normales de la página se cargan como parte del navegador. `raw/` guarda un snapshot del DOM renderizado, etiquetado `acquired_representation=rendered_dom`; no se presenta como los bytes HTML originales del servidor. XML identificado por extensión o `outputType=xml` sigue usando el transporte HTTP.

La configuración y el manifiesto registran el transporte y el canal, y el checkpoint distingue este modo de HTTP. Reutilizar una carpeta con otro transporte exige crear una salida nueva. No se cambia el período científico ni los criterios del exportado.

Validación local de esta versión: 61 pruebas del scraper aprobadas, incluidas las de navegador con driver/red simulados, pausa para verificación humana, límites, rechazo de perfiles personales, conservación de la sesión sin exportar cookies y persistencia del manifiesto antes del primer intento remoto. Esto no constituye una validación de adquisición de Reuters con navegador real.

#### Resultado de la prueba real de navegador

Se abrió Edge visible con el perfil propio del scraper. Se observó HTTP 401 para la semilla `/business/`, se inició la espera de verificación manual y otra navegación del documento principal volvió a recibir 401. El investigador informó que la verificación o el bloqueo persistía. Se interrumpió la prueba; no se obtuvo ningún documento de noticia.

Los [registros de la prueba](../output/reuters_browser_20261021T205813351Z/runs/20261021T205815_1ea7ab15/http.jsonl) y una [anotación externa del resultado](../output/reuters_browser_20261021T205813351Z/operator_outcome.json) se conservaron. La interrupción externa terminó el proceso antes de generar el manifiesto/resumen final de esa corrida: no se presenta como una ejecución completa ni se inventan conteos de recursos secundarios. La nueva versión escribe el manifiesto inicial antes de realizar solicitudes, para preservar configuración y dependencias aunque el proceso termine de forma abrupta.

Se comprobó que no quedaban el proceso Python de la prueba ni el navegador asociado al perfil, y se retira únicamente el bloqueo de escritura obsoleto de esa carpeta. El perfil se conserva localmente; no se exportan sus cookies. El resultado indica que un navegador automatizado convencional con perfil persistente no bastó en esta prueba; la descarga real sigue pendiente.
