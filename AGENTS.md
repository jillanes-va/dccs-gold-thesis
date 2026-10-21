# AGENTS.md — DCCS Gold Thesis

> Instrucciones para agentes que trabajen en este repositorio. Leer también `README.md` y los documentos de `docs/`. Si existe un conflicto entre estas instrucciones y una decisión explícita y reciente del investigador, señalarlo antes de actuar.

## 1. Propósito y límites del proyecto

Este repositorio apoya una **plataforma de investigación general sobre noticias económicas, financieras y políticas y su relación con mercados de commodities**. El oro es una aplicación científica central, pero la adquisición y organización del corpus deben poder reutilizarse para otros activos. La arquitectura no debe presuponer que todas las noticias mencionarán un commodity o un ticker.

La plataforma de datos y las aplicaciones econométricas son trabajos relacionados, pero distintos. No confundir un experimento de ingeniería (por ejemplo, probar un scraper) con evidencia científica sobre precios.

**Prioridades, en orden:** validez científica y reproducibilidad; trazabilidad; legibilidad y separación de responsabilidades; simplicidad proporcional al problema; rendimiento y extensibilidad cuando haya evidencia de que son necesarios.

## 2. Autonomía del agente

**Puede actuar sin consulta adicional para:** diagnosticar errores; refactorizar conservando el comportamiento; introducir pruebas; mejorar logging, validación, documentación técnica y configuración; ejecutar pruebas locales acotadas; y proponer alternativas de arquitectura.

**Debe obtener aprobación expresa antes de:** cambiar una hipótesis o pregunta científica; elegir o reemplazar una especificación econométrica; definir o cambiar variables, retornos, volatilidad o sentimiento; modificar períodos, universos de noticias o criterios de inclusión; diseñar reglas definitivas de relevancia directa/indirecta; iniciar recolección a gran escala; asumir costos; usar servicios con credenciales nuevas; realizar cambios destructivos; o efectuar operaciones sensibles con terceros.

**Control de versiones:** no realizar `commit`, `push`, `merge`, `rebase` destructivo ni cambiar `main` sin autorización explícita. Trabajar preferentemente en una rama de propósito único y presentar los cambios para revisión. Una petición concreta de crear archivos o una PR autoriza únicamente las acciones incluidas en ese alcance, no fusionar la PR.

Si aparece una ambigüedad científica, detener esa decisión y exponer opciones, supuestos y consecuencias; avanzar con las partes puramente técnicas que no dependan de ella.

## 3. Principios de implementación

- **Resolver primero de forma simple.** Preferir bibliotecas maduras, funciones pequeñas y configuraciones explícitas. No crear capas, servicios distribuidos, bases de datos o modelos complejos por anticipación.
- **Separar tareas según necesidad real:** descubrimiento de URLs, solicitud HTTP/API, extracción, normalización, validación, almacenamiento, NLP, modelado y visualización. No fragmentar artificialmente un script trivial.
- Mantener el código legible y las dependencias justificadas. Evitar refactorizaciones no relacionadas con la tarea.
- No sacrificar corrección, medición de cobertura o procedencia para ganar velocidad.
- Conservar las interfaces existentes cuando sea razonable; indicar cualquier cambio incompatible.
- Usar español en informes y documentación científica; identificadores en inglés son apropiados.

## 4. Entorno y estado real del repositorio

- Python administrado con `uv`; `.python-version` declara **3.11** y `pyproject.toml` restringe a `>=3.11,<3.13`. Utilizar `uv sync` y `uv run` cuando proceda.
- R se contempla para inferencia y econometría, pero los scripts `r_models/` que menciona el README **no estaban presentes en `main` al 2026-10-21**.
- La estructura verificada en esa fecha incluye `src/pilot.py`, `main.py`, `notebooks/` y `output/`. El README también describe rutas futuras. No dar por existentes `data/`, `docs/`, `tests/` u otros módulos sin comprobarlo.
- `src/pilot.py` es un piloto, **no un pipeline validado** de adquisición de 2026. La salida conocida muestra fallos en la etapa de comprobación de `robots.txt`; no equivale a una evaluación del acceso efectivo a artículos.
- El repositorio contiene notebooks exploratorios y algunos archivos de salida versionados. No borrarlos ni tratarlos como resultados científicamente verificados.

## 5. Reproducibilidad y auditoría

- Registrar versión del código, dependencias, fecha de ejecución, configuración, semillas aleatorias y entorno/hardware cuando afecten el resultado.
- Mantener datos originales inmutables. Diferenciar `raw`, `intermediate` y `processed` cuando esas rutas existan.
- Preservar historial de transformaciones; no ajustar resultados manualmente ni corregir datos silenciosamente.
- Para procesos aleatorios, fijar semilla e informar fuentes remanentes de no determinismo.
- Para modelos econométricos, registrar muestra, reglas de filtrado, especificación, horizontes, controles, errores estándar y correcciones por pruebas múltiples cuando correspondan.
- Distinguir resultados ejecutados/validados de simulaciones, aproximaciones, hipótesis y tareas pendientes.
- No afirmar que algo corre, es reproducible o fue validado sin haberlo comprobado.

## 6. Corpus de noticias y datos de mercado

Preservar, cuando existan: URL canónica, identificador, título, texto, idioma, fecha/hora y zona horaria de publicación, fecha/hora de recuperación, **fuente editorial original**, **plataforma de adquisición**, tipo de documento, estado de acceso, hash del texto, versión y método de extracción. Mantener explícitos los valores faltantes y los niveles de confianza de metadatos inferidos.

- Separar **universo adquirido**, noticias potencialmente relevantes, noticias clasificadas y muestra analítica.
- No imponer por defecto un filtro anticipado de commodities a la adquisición general: el corpus puede servir para estudiar canales directos e indirectos.
- Una noticia puede relacionarse con múltiples commodities. No confundir relevancia temática, mecanismo económico supuesto, signo esperado y efecto identificado estadísticamente.
- Distinguir duplicados exactos, republicaciones, versiones actualizadas y cobertura independiente del mismo evento.
- Para precios, preservar tipo de instrumento (spot/futuro), símbolo, moneda, unidad, mercado, vencimiento, criterio de continuidad/roll y calendario. Evitar contaminación de información futura y anticipar cierres bursátiles diferentes.
- La cobertura recopilada **no es** el universo completo de lo publicado; cuantificar cobertura, sesgos de fuente y faltantes por año cuando sea posible.

## 7. Scraping, APIs y exploración técnica

La misión del agente es **explorar activamente rutas técnicas viables**, no abandonar una fuente ante el primer obstáculo. Puede estudiar documentación, feeds, sitemaps, endpoints públicos, peticiones de red, navegadores automatizados, APIs, datasets históricos, archivos web y bibliotecas de extracción; comparar enfoques y preparar pilotos reproducibles.

Separar **investigar/proponer** de **ejecutar**. Antes de métodos nuevos que impliquen restricciones de acceso, costos, riesgos contractuales, impacto operativo, credenciales o volumen importante, explicar mecanismo, ventajas, límites y consecuencias, y solicitar aprobación explícita. La aprobación del investigador no reemplaza permisos exigidos por terceros: no acceder sin autorización a recursos privados, no eludir autenticación o paywalls ni interferir con mecanismos de seguridad.

En las pruebas autorizadas:
- Registrar solicitudes exitosas y fallidas, redirecciones, códigos HTTP, timestamps y razones de exclusión.
- Diferenciar `robots.txt` explícitamente restrictivo, error al consultarlo, conectividad, rate limiting, bloqueo y fallo de parser. No agrupar todo bajo «scraping imposible».
- Aplicar límites de tasa, timeouts, backoff y no sobrecargar servidores.
- Evitar solicitudes repetidas; soportar checkpoints/reanudación para tareas grandes.
- Probar muestras pequeñas, diversas en fechas y medios, antes de escalar.
- Identificar claramente qué información se obtuvo de APIs oficiales, archivos, scraping HTML o fuentes secundarias.
- Documentar términos de uso, licencias, redistribución y limitaciones conocidas. No subir textos sujetos a restricciones ni credenciales al repositorio.

## 8. Inferencia y decisiones científicas

No favorecer especificaciones solo porque arrojen significancia. Preservar resultados nulos o desfavorables. Distinguir asociación, predicción y causalidad. Evitar filtración temporal, sesgo de selección retrospectiva y sobreajuste por selección de variables/horizontes. Documentar explícitamente sincronización noticia-mercado y criterios de validación fuera de muestra.

El modelo y los resultados previos sobre oro pueden servir de antecedente; **no asumir que son la especificación definitiva de la plataforma**. Revisar `docs/methodology.md` y `docs/decisions.md` para distinguir lo decidido de lo exploratorio.

## 9. Rutina de trabajo

**Antes:** inspeccionar código y documentación relevante; delimitar objetivos; indicar qué cambiará y qué riesgos metodológicos existen.

**Durante:** modificar el mínimo de archivos necesarios; mantener separación de tareas; producir logs legibles; introducir tests cuando cambie comportamiento.

**Después:** ejecutar comprobaciones posibles; enumerar archivos tocados; informar resultados y fallos; señalar supuestos, incertidumbre y tareas posteriores. Nunca reportar como ejecutado algo que no se pudo ejecutar.

Preferir pruebas unitarias reproducibles sin internet, además de pruebas de integración con red únicamente cuando estén autorizadas. Para adquisiciones remotas, registrar también el denominador de intentos fallidos.
