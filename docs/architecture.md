# Arquitectura técnica — estado y propuesta

**Actualizado:** 2026-10-21.  
**Estado:** describe por separado lo verificado en `main` y una arquitectura objetivo **no implementada**.

## 1. Principio arquitectónico

Una plataforma reutilizable de noticias y commodities: adquisición general independiente del activo; información textual normalizada y conservada; enriquecimiento semántico y construcción de paneles de mercado como transformaciones posteriores.

Aplicar el criterio de la **solución más simple suficiente**. No introducir orquestadores, colas, infraestructuras distribuidas o bases externas antes de verificar su necesidad con volumen, rendimiento y estabilidad reales.

## 2. Estructura observada en `main` al 2026-10-21

```text
dccs-gold-thesis/
├── .gitignore
├── .python-version
├── README.md
├── main.py
├── pyproject.toml
├── uv.lock
├── src/
│   └── pilot.py
├── notebooks/
│   ├── descarga.ipynb
│   ├── exploracion.ipynb
│   ├── news_api.ipynb
│   └── noticias_familias.jsonl
└── output/
    ├── articles.jsonl
    ├── attempts.csv
    └── summary.json
```

- `main.py` contiene una entrada de ejemplo, no el pipeline de tesis completo.
- `src/pilot.py` integra descubrimiento inicial, consulta HTTP, verificación de acceso, extracción y salidas; su ejecución conocida no recuperó artículos.
- Los notebooks son exploratorios; no se verificó su reproductibilidad integral en esta revisión.
- `output/` tiene archivos versionados; debe evaluarse cuándo conviene ignorar resultados futuros y preservar solo ejemplos pequeños, sin borrar los actuales unilateralmente.
- El README declara una arquitectura Python → R y rutas propuestas, pero no todas existen en la rama actual.

## 3. Arquitectura lógica objetivo (propuesta)

```text
Fuentes y archivos
      │
      ▼
[1] Descubrimiento de URLs / índices / API
      │
      ▼
[2] Adquisición HTTP/API con logs y reintentos controlados
      │
      ▼
[3] Extracción: texto, metadatos, timestamps
      │
      ▼
[4] Normalización, validación, deduplicación y procedencia
      │
      ├──────────────► Corpus maestro (no filtrado por commodity)
      │                        │
      │                        ▼
      │                 [5] NLP y etiquetado
      │                        │
      │                        ▼
      │                 Asociación noticia-activo
      │                        │
      ▼                        ▼
[6] Precios y series ──► [7] Panel temporal reproducible
                                  │
                                  ▼
                         [8] Modelos / inferencia
                                  │
                                  ▼
                           Tablas y figuras
```

Cada paso debería disponer de entradas, salidas, configuración, errores y pruebas definidas. Implementar gradualmente y no crear carpetas vacías por anticipación.

## 4. Organización de carpetas posible (no obligatoria)

```text
src/
  discovery/      # feeds, índices, sitemaps, fuentes históricas
  acquisition/    # HTTP/API, límites, checkpoints, errores
  extraction/     # contenido y metadatos
  processing/     # limpieza, deduplicación, calidad
  nlp/            # etiquetas, embeddings, sentimiento (si se aprueba)
  markets/        # ingestión y alineación de precios
  panels/         # agregaciones y datasets analíticos
configs/          # parámetros de ejecuciones
scripts/          # comandos de entrada
r_models/         # inferencia en R cuando se implemente
tests/            # pruebas unitarias y de integración controlada
docs/             # metodología, fuentes, decisiones, arquitectura
data/             # datos no versionados, según derechos
```

No migrar `src/pilot.py` a esta estructura sin una necesidad técnica concreta. Refactorizar de forma incremental y probada.

## 5. Contratos de datos sugeridos

### Tabla `articles`

Clave primaria `article_id` estable. Campos recomendados: `canonical_url`, `title`, `body`, `language`, `published_at_utc`, `first_seen_at_utc`, `editorial_publisher`, `source_platform`, `content_hash`, `extraction_method`, `run_id`, `metadata_confidence`.

### Tabla `acquisition_attempts`

Clave `attempt_id`; incluir `run_id`, URL, origen de descubrimiento, fecha de intento, resultado de `robots.txt` si procede, código HTTP, redirect, error y duración. Una fila por intento, aunque no haya artículo.

### Tabla `article_commodity`

`article_id`, `commodity_id`, `relation_type` (`direct`, `indirect`, `uncertain`), `event_type`, `method`, `model_version`, `confidence`, `review_status`. **Taxonomía provisional.** Una noticia puede tener múltiples relaciones.

### Tabla `market_prices`

`asset_id`, `market`, `instrument_type`, `contract`, `timestamp_utc`, `price`, `currency`, `unit`, `data_provider`, `adjustment_method`. Especificar reglas de precios continuos y ajustes antes de modelar retornos.

### Tabla `analysis_panels`

Derivada, no fuente original. Contener `asset_id`, fecha/horizonte, claves de versión de corpus/precios, reglas de agregación y variables explicativas/de respuesta con definición trazable.

## 6. Formatos y escalamiento

**Piloto:** CSV para auditorías pequeñas y JSONL para artículos son aceptables. Mantener identificadores y esquema estable. Para volúmenes altos, evaluar Parquet particionado por fecha/fuente y lectura por lotes antes de proponer una base de datos compleja.

No almacenar secretos en archivos versionados. Definir políticas de versionado, respaldos, retención y redistribución según tamaño y derechos. Los notebooks deben consumir módulos reutilizables en lo posible, no convertirse en la única definición del pipeline.

## 7. Calidad y observabilidad

- Contar denominadores en cada etapa: URLs descubiertas, probadas, permitidas, descargadas, parseadas, fechadas y válidas.
- Registrar por clase de error y fuente; no perder fallos por reemplazar un CSV de auditoría al repetir un experimento.
- Identificar versión de parser, configuración y ejecución para comparar corridas.
- Validar claves, timestamps, duplicados, texto vacío y formatos de precio.
- Introducir tests unitarios locales para URL, fecha, metadatos y normalización, y tests de integración acotados con autorización.

## 8. Plan incremental recomendado (propuesto)

1. **Auditar `src/pilot.py` y su salida**, identificar exactamente por qué falló la etapa robots/red sin modificar reglas científicas.
2. Incorporar logging de fallos diferenciados, fixtures HTML locales y pruebas unitarias.
3. Validar extracción de pequeñas muestras por fuente, cubriendo varias fechas de 2026, sujeto a accesos autorizados.
4. Definir el esquema del corpus y preservar trazabilidad; mantener corpus sin filtros temáticos iniciales.
5. Evaluar rendimiento, sesgo de cobertura y conveniencia de otras rutas de adquisición.
6. Diseñar y validar clasificación de noticias y su posterior vinculación con precios.

**No se marca ninguna de estas fases como completada** por el mero hecho de incluirla en esta propuesta.
