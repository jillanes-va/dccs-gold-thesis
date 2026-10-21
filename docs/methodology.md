# Metodología de investigación — borrador vivo

**Estado:** documento de trabajo, no protocolo preregistrado ni metodología aprobada en su totalidad.  
**Actualizado:** 2026-10-21.  
**Ámbito:** plataforma general de noticias y commodities, con oro como aplicación prioritaria.

## 1. Objetivos y preguntas

### Objetivo de infraestructura (decidido)

Construir una plataforma reproducible para recuperar, armonizar, preservar y analizar noticias financieras, económicas y políticas provenientes de múltiples fuentes. La arquitectura debe poder estudiar distintos commodities sin reconstruir el corpus para cada uno.

### Preguntas científicas posibles (abiertas)

- ¿Qué contenido de las noticias está asociado con retornos y/o volatilidad futuros de distintos commodities?
- ¿Difieren las asociaciones entre noticias que mencionan directamente el commodity y noticias macroeconómicas o geopolíticas con relación indirecta?
- ¿Cambian los patrones por fuente editorial, época, mercado, tipo de acontecimiento o activo?
- ¿Qué diferencias producen medidas de sentimiento basadas en diccionarios, modelos financieros y temas/eventos?

**Importante:** no se afirma causalidad ni predictibilidad antes de pruebas rigurosas. El objetivo definitivo, hipótesis confirmatorias y estimandos deben ser aprobados por el investigador.

## 2. Unidades de observación

No mezclar las unidades de análisis:

1. **Documento/noticia:** publicación, versión, origen editorial, texto y timestamps.
2. **Acontecimiento:** conjunto de documentos que narran el mismo evento; requiere una regla de agrupamiento por definir.
3. **Activo/commodity:** serie de precios spot o futuros con identificadores y contratos bien especificados.
4. **Panel activo-fecha/horizonte:** agregación de señales textuales y resultados financieros.

Una noticia puede asociarse a varios activos y aparecer en varias plataformas. Se recomienda relación muchos-a-muchos entre `article_id` y `commodity_id`.

## 3. Adquisición y cobertura (en evaluación)

### Universo de referencia

Ideal: todas las noticias publicadas en medios seleccionados durante una ventana temporal determinada. Universo **observado**: todas las noticias efectivamente recuperables por procedimientos documentados; puede ser un subconjunto sesgado del universo ideal.

### Piloto inicial (exploratorio)

- Periodo propuesto en conversaciones: publicaciones de **2026**.
- Plataformas candidatas: Reuters, Bloomberg, Benzinga y Yahoo Finance; este último es también agregador, por lo que requiere atribución editorial.
- Prioridad: cobertura general, sin filtros iniciales por commodity.
- La prueba actual de `src/pilot.py` no verificó la recuperación de artículos; se detuvo al consultar reglas de acceso. El fallo es **técnico pendiente de diagnóstico**, no evidencia de cobertura nula.

El diseño del muestreo del piloto (fechas, tamaño y criterios de éxito) **no está aprobado definitivamente**. Antes de evaluar una fuente, distinguir recuperación de URLs, acceso al HTML, disponibilidad de texto, validez de fecha, duplicación y consistencia entre meses.

## 4. Variables textuales (por decidir)

Conservar texto y metadatos originales antes de derivar variables:

- **Mención directa:** el artículo se refiere explícitamente al commodity o su mercado.
- **Relación indirecta:** describe acontecimientos con mecanismo económico plausible para el commodity, aun sin mencionarlo; requiere taxonomía y etiquetado documentados.
- **Tema/evento:** política monetaria, shocks de oferta/demanda, actividad industrial, conflicto geopolítico, clima, etc.; categorías tentativas, no exhaustivas.
- **Sentimiento textual:** valor evaluativo del texto (p. ej. LM o FinBERT), distinto de su efecto sobre precios.
- **Novedad, difusión y atención:** variables candidatas; separar artículos originales, republicaciones y modificaciones.

No seleccionar retrospectivamente noticias o categorías a partir de retornos observados y luego evaluar su predictibilidad sobre los mismos datos. Si se requiere aprendizaje supervisado, separar entrenamiento/validación/prueba por tiempo y, según diseño, por medio o evento.

## 5. Series financieras (alcance abierto)

La investigación sobre oro contempla mercados spot y derivados; el README menciona LBMA, COMEX y posibles extensiones a SGE/SHFE, además de controles como TIPS y dólar. **No interpretar esta lista como datos ya integrados y validados.** La plataforma podrá extenderse a cobre, petróleo, trigo u otros commodities previa decisión científica.

Registrar siempre:

- Mercado, instrumento, contrato/vencimiento, divisa, unidad y proveedor de precios.
- Ajustes por continuidad y rollover en futuros; evitar retornos espurios.
- Calendarios, zona horaria, cierre de mercado y horario de difusión.
- Valores faltantes, reglas de interpolación (si se aprueban) y transformaciones.

Candidata a retorno logarítmico diario: `r_t = 100 · [log(P_t) − log(P_{t−1})]` para una serie de precios definida de manera consistente. La definición de precios y horizontes requiere validación antes de usar la fórmula como especificación oficial.

## 6. Estrategia estadística — posibilidades, no compromisos

- Describir el corpus por fuente y tiempo, disponibilidad de textos completos, duplicados, idiomas y cobertura.
- Construir agregaciones temporales con reglas explícitas para noticias antes y después del cierre bursátil.
- Explorar relaciones con retornos y volatilidad; considerar controles macroeconómicos y dependencias temporales según la pregunta.
- Contemplar errores estándar adecuados para series de tiempo, multiplicidad de hipótesis, análisis de sensibilidad y evaluación fuera de muestra cuando proceda.
- Separar experimentos exploratorios de inferencia confirmatoria; conservar resultados negativos.

**Antecedente del proyecto del oro:** se han explorado señales LM y FinBERT, respuestas de retornos por horizontes y modelos de volatilidad. Es un antecedente de trabajo, no una obligación de aplicar exactamente esas especificaciones al corpus ampliado.

## 7. Amenazas a la validez

1. **Selección editorial:** medios y temáticas representados no son una muestra neutral de los eventos del mundo.
2. **Sesgo de disponibilidad histórica:** faltantes, cambios de diseño web, coberturas heterogéneas.
3. **Duplicación/republicación:** conteos inflados y dependencia entre observaciones.
4. **Look-ahead y timestamp:** fecha de publicación distinta de primera disponibilidad efectiva.
5. **Confusión de sentimiento y shock económico:** un tono negativo puede acompañar aumentos de precio.
6. **Endogeneidad y noticias que reaccionan al precio:** atención mediática y retornos pueden determinarse conjuntamente.
7. **Multiplicidad:** varios activos, categorías, ventanas, horizontes y modelos incrementan falsos positivos.
8. **Deriva temporal:** modelos de lenguaje, mercados y fuentes cambian a lo largo del tiempo.

## 8. Criterios de salida por fase (propuestos)

| Fase | Evidencia exigible |
|---|---|
| Adquisición piloto | URLs elegibles, intentos totales, fallos por causa, textos completos, tasas por medio/mes |
| Corpus normalizado | Esquema estable, claves y hashes, cobertura, deduplicación, procedencia auditable |
| Etiquetado | Taxonomía documentada, muestra anotada, acuerdo/errores, recall de filtros |
| Panel financiero | Contratos/precios verificables, calendario explícito, reglas de agregación, auditorías |
| Inferencia | Código ejecutable, especificación congelada, tablas/gráficos reproducibles, limitaciones |

Para registrar decisiones cerradas o cambios de protocolo, actualizar `docs/decisions.md` con fecha y justificación.
