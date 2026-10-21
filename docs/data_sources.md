# Fuentes de datos y procedencia

**Estado:** inventario inicial de candidatas, no garantía de acceso, licencia o cobertura.  
**Actualizado:** 2026-10-21.

## 1. Convenciones del inventario

Registrar por cada fuente: responsable editorial, distribuidor, producto o dominio, método de acceso, periodo reclamado, periodo **verificado**, contenido recuperable (URL/titular/cuerpo), horarios, idioma, términos/licencia, costo, restricciones, evidencia de prueba y sesgos de cobertura.

Separar:

- **Fuente editorial original**: organización que redactó la noticia.
- **Plataforma de adquisición**: API, portal, agregador o archivo desde el que se obtuvo.
- **Dataset secundario**: corpus preexistente compilado por terceros, que puede mezclar medios.

Una noticia de Reuters encontrada en Yahoo Finance conserva *Reuters* como fuente editorial y *Yahoo Finance* como plataforma de adquisición.

## 2. Candidatas iniciales de noticias

| Fuente/plataforma | Naturaleza | Método a investigar | Estado en el proyecto | Precaución |
|---|---|---|---|---|
| Reuters | Agencia internacional original | Web pública, productos/APIs autorizados, archivos históricos y corpus académicos | Candidata; no validada | Acceso y derechos varían por producto; republicaciones |
| Bloomberg | Productor original de noticias financieras | Portal, licencias/archivos, datasets históricos | Candidata; no validada | Barreras de acceso y costes potenciales |
| Benzinga | Medio e información especializada en mercados | Web y API/productos de noticias | Candidata; no validada | Enfoque bursátil; cobertura general desigual |
| Yahoo Finance | Portal/agregador y productor de contenido | Índices públicos, web y productos de datos | Candidata; no validada | No equivale a medio independiente por artículo |
| Dow Jones / WSJ | Productor/distribuidor de noticias financieras | Archivos y productos con derechos de acceso | Antecedente de investigación en oro; no parte del piloto actual | Derechos y cobertura histórica |
| Common Crawl | Archivo de páginas web, no editor | Índices, WARC/WAT/WET | Posible alternativa; no integrada | Captura incompleta, ruido, derechos de textos originales |
| FNSPID | Dataset académico multifuente | Descarga y auditoría de sus archivos | Referencia técnica; no integrado | Selección original centrada en empresas; cobertura heterogénea |

**No se han medido aquí** disponibilidad histórica, completitud de texto ni tasas de extracción de estas fuentes. Toda valoración de viabilidad debe derivarse de pruebas reproducibles.

## 3. Antecedentes de FNSPID

El trabajo *FNSPID: A Comprehensive Financial News Dataset in Time Series* (Dong, Fan y Peng, 2024) es una referencia para el diseño de extracción y compilación. Se ha discutido la integración de contenidos de Nasdaq y corpus históricos asociados a Reuters, Bloomberg, Benzinga y Lenta.ru. La relación entre registros, fechas, texto disponible y fuente original requiere auditoría independiente antes de reutilizar datos.

Referencias de partida:

- [Preprint](https://arxiv.org/abs/2402.06698)
- [Repositorio](https://github.com/Zdong104/FNSPID_Financial_News_Dataset)

No confundir el proveedor de cotizaciones utilizado por un artículo académico con la procedencia de las noticias.

## 4. Fuentes financieras y series de mercado

El README menciona, como alcance del proyecto del oro, COMEX, LBMA, SGE, SHFE y variables macroeconómicas como TIPS y dólar. La presencia de esos nombres en el README **no valida** descarga, integridad o uso de las series en el código actual.

Para cada serie documentar:

| Campo | Ejemplo de información necesaria |
|---|---|
| `series_id` | Identificador local único |
| `provider` | Proveedor/API/archivo de origen |
| `market` | Mercado y jurisdicción |
| `instrument_type` | Spot, fixing, futuro, índice, tipo de cambio |
| `contract` | Símbolo, vencimiento, regla de rollover si corresponde |
| `currency` / `unit` | USD/onza troy, RMB/gramo, etc. |
| `timezone` / `calendar` | Calendario de observación y zona horaria |
| `availability` | Fechas, huecos, revisiones y acceso efectivo |
| `license` | Restricciones de uso y redistribución |
| `transformations` | Ajustes, conversiones, sincronización y retorno |

## 5. Auditoría mínima para el piloto de adquisición

Capturar **antes de decidir si una fuente es viable**:

- `source_id`, `discovery_platform`, `editorial_publisher`, `discovery_url`, `article_url`, `canonical_url`.
- `attempted_at_utc`, `fetched_at_utc`, `published_at`, `published_timezone`, `date_confidence`.
- `http_status`, `robots_status`, `fetch_status`, `parse_status`, `failure_reason`.
- `title`, `language`, `author`, `body_available`, `word_count`, `content_hash`.
- `extraction_method`, `schema_version`, `run_id`, `software_version`.

Registrar denominadores: semillas examinadas, URLs encontradas, URLs únicas, solicitudes intentadas, respuestas válidas, artículos fechados y textos recuperados. Desglosar por dominio, mes, tipo de fallo e idioma.

**Diagnóstico actual:** la salida de `src/pilot.py` reportó `discovery_robots_disallowed_or_unavailable` para las cuatro plataformas. Ese estado agrega fallos diferentes y, sin códigos y detalles separados, no permite concluir que `robots.txt` prohíba expresamente todos los accesos.

## 6. Control de calidad y sesgos

- Deduplicar URL canónica y contenido, pero conservar trazas de todas las republicaciones y versiones.
- Tratar la ausencia de fecha de publicación de forma explícita: no sustituirla silenciosamente por fecha de scraping.
- Medir artículos cortos, contenido incompleto, idiomas inesperados y contenido no periodístico.
- Documentar cambios de HTML/APIs entre años.
- No inferir cobertura completa a partir de un sitemap, RSS o archivo de terceros.
- No redistribuir texto íntegro sin verificar licencias y derechos correspondientes.

## 7. Plantilla para añadir una fuente

```md
### Nombre de fuente / producto
- Medio editorial / plataforma de adquisición:
- Dominio o endpoint:
- Método autorizado de recuperación:
- Fechas de cobertura declaradas / verificadas:
- Tipo de contenido (metadatos, titulares, texto completo):
- Idiomas / zonas horarias:
- Derechos, credenciales y costos:
- Prueba realizada (fecha, comando, tamaño):
- URLs elegibles / intentadas / exitosas:
- Errores y faltantes:
- Principales sesgos:
- Evidencia (commit, log, informe):
- Estado: candidata / piloto / validada / suspendida
```
