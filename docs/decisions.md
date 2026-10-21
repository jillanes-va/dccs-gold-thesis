# Registro de decisiones del proyecto

**Propósito:** conservar qué se decidió, por qué y cuáles alternativas siguen abiertas. Este registro **no sustituye** resultados de experimentos ni evidencia de funcionamiento.  
**Actualizado:** 2026-10-21.

## Convenciones

- **Aprobada:** instrucción o preferencia confirmada por el investigador.
- **Propuesta:** recomendación pendiente de aceptación.
- **Exploratoria:** hipótesis o método en evaluación, no especificación fija.
- **Pendiente:** se requiere evidencia o decisión nueva.
- Toda entrada futura debería incluir fecha, decisión, justificación, alternativas, impacto, responsable y evidencia enlazable (PR/commit/datos).

## Decisiones aprobadas

### D-001 · Alcance general de la plataforma

- **Fecha:** 2026-10-21.
- **Estado:** aprobada.
- **Decisión:** el repositorio debe evolucionar hacia una plataforma general de noticias y commodities. La tesis sobre el oro sigue siendo una aplicación importante, no una restricción rígida sobre arquitectura o corpus.
- **Razón:** facilitar comparaciones y reutilización con múltiples activos y canales informativos.
- **Impacto:** adquisición y metadatos independientes del ticker o commodity; aplicaciones financieras en capas posteriores.

### D-002 · Autonomía técnica con control científico

- **Fecha:** 2026-10-21.
- **Estado:** aprobada.
- **Decisión:** el agente puede actuar autónomamente en ingeniería cotidiana; debe pedir aprobación para cambios con consecuencias metodológicas o científicas.
- **Razón:** reducir iteración manual sin delegar decisiones académicas.
- **Impacto:** tareas bien delimitadas, cambios revisables y justificación de elecciones científicas.

### D-003 · Prioridades de implementación

- **Fecha:** 2026-10-21.
- **Estado:** aprobada.
- **Decisión:** reproducibilidad, legibilidad, división razonable de responsabilidades y solución más simple adecuada al problema; admitir complejidad cuando se justifique.
- **Impacto:** pruebas pequeñas, modularidad sin sobreingeniería, cambios mínimos y trazabilidad.

### D-004 · Exploración amplia de adquisición

- **Fecha:** 2026-10-21.
- **Estado:** aprobada, condicionada a aprobación de operaciones sensibles.
- **Decisión:** el agente debe investigar activamente alternativas técnicas para obtener noticias, incluyendo APIs, scraping, archivos, datasets y nuevas rutas de descubrimiento. Debe pedir aprobación previa para acciones de riesgo, costos, cambios relevantes de acceso o grandes volúmenes.
- **Límite:** aprobar una estrategia no concede autorización sobre recursos de terceros que requieran permisos. Respetar requisitos de acceso aplicables.
- **Razón:** la viabilidad de adquisición es una pregunta de ingeniería del propio proyecto.

## Líneas exploratorias y decisiones pendientes

### E-001 · Piloto 2026 con cuatro plataformas

- **Estado:** exploratoria.
- **Idea:** estudiar Reuters, Bloomberg, Benzinga y Yahoo Finance durante 2026 como prueba de adquisición general de noticias; no comenzar necesariamente filtrando por commodities.
- **Evidencia actual:** `src/pilot.py` implementa semillas y lógica básica; los intentos disponibles informaron fallo en verificación de `robots.txt`. No hay evidencia concluyente de extracción de artículos completos.
- **Pendiente:** diagnóstico por dominio, selección temporal reproducible, alcance del piloto, métricas de cobertura y medios originales.

### E-002 · Noticias directas e indirectas

- **Estado:** exploratoria.
- **Idea:** etiquetar noticias que mencionan explícitamente activos y noticias sobre eventos económicos con mecanismos plausibles de influencia.
- **Pendiente:** definiciones operacionales, anotación humana y validación de errores; evitar clasificación retrospectiva condicionada en precios.

### E-003 · Extensión a commodities adicionales

- **Estado:** exploratoria.
- **Idea:** comparar oro con mercados industriales, energéticos o agrícolas, sin imponer selección fija hasta verificar datos y preguntas científicas.
- **Pendiente:** lista de activos, proveedor de precios, contratos, moneda, calendario y objetivo inferencial.

### E-004 · Modelado estadístico

- **Estado:** pendiente.
- **Idea:** desarrollar econometría y/o modelos predictivos según pregunta científica, separando retorno, volatilidad y explicación de mecanismos.
- **Pendiente:** especificación aprobada, estrategia de identificación, división temporal, controles, corrección por multiplicidad y criterios de reporte.

### E-005 · Política de almacenamiento y redistribución

- **Estado:** pendiente.
- **Idea:** preservar texto bruto y procedencia en almacenamiento apropiado, no necesariamente Git.
- **Pendiente:** evaluar licencias por fuente, esquemas de metadatos, formatos y estrategias de backups.

## Registro de cambios futuros

Copiar la siguiente plantilla cuando se cierre una nueva decisión:

```md
### D-XXX · Título
- **Fecha:** AAAA-MM-DD
- **Estado:** aprobada / modificada / revocada
- **Decisión:** ...
- **Justificación y alternativas:** ...
- **Impacto técnico y científico:** ...
- **Evidencia o referencia:** ...
- **Revisión posterior:** ...
```
