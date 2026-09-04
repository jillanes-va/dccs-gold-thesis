# Relaciones Texto-Finanzas sobre el Precio del Oro [WIP]

[![Project Status: WIP](https://img.shields.io/badge/Status-Work_in_Progress-yellow.svg)](https://github.com/jillanes-va/dccs-gold-thesis) [![Python: \>=3.11](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/) [![Package Manager: uv](https://img.shields.io/badge/Environment-uv-purple.svg)](https://github.com/astral-sh/uv) [![R: \>=4.3](https://img.shields.io/badge/Analysis-R-blue.svg)](https://www.r-project.org/) [![Institution: DCCS UDD](https://img.shields.io/badge/Institution-DCCS_UDD-red.svg)](https://dccs.udd.cl/) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Repositorio de investigación doctoral enfocado en caracterizar, modelar y contrastar la relación empírica entre las dinámicas discursivas/narrativas en fuentes de texto y la microestructura de precios del oro y sus derivados financieros.

------------------------------------------------------------------------

## Información Académica

- **Programa:** Doctorado en Ciencias de la Complejidad Social (DCCS)
- **Institución:** Universidad del Desarrollo (UDD), Santiago, Chile
- **Investigador:** Juan Illanes (`jillanes-va`)
- **Equipo de Supervisión:**
  - Dr. Juan Pablo Couyoumdjian (Facultad de Gobierno, UDD)
  - Dra. María Paz Raveau (Facultad de Ingeniería / Faro UDD)
  - *Nota: Asignación formal de roles de profesor guía y co-guía en proceso de definición administrativa.*

------------------------------------------------------------------------

## Pregunta e Hipótesis de Investigación

### Pregunta Central

¿La descripción narrativa del oro en medios textuales tiene un efecto apreciable y medible sobre el precio del oro y sus derivados financieros?

### Hipótesis de Trabajo [WIP]

Un constructo cuantitativo y verificable derivado del procesamiento de texto (análisis de sentimiento, modelado de tópicos o entropía discursiva) correlaciona de forma estadísticamente significativa con los retornos no explicados y/o los regímenes de volatilidad del oro y sus instrumentos derivados.

------------------------------------------------------------------------

## Alcance Empírico y Activos de Estudio [WIP]

El proyecto evalúa la transmisión de información y narrativas sobre diferentes plataformas de negociación globales:

- **Mercado Spot (Contado Físico):**
  - Londres (LBMA - Subasta oficial Fixing AM/PM)
  - Shanghái (SGE - Shanghai Gold Exchange, e.g., contrato Au99.99) [WIP]
- **Mercado de Derivados (Futuros):**
  - Nueva York (COMEX - Contratos `GC` continuos)
  - Shanghái (SHFE - Shanghai Futures Exchange, contrato `au0`) [WIP]
- **Variables de Contraste y Control Macroeconómico [WIP]:**
  - Tasas de interés reales (TIPS de EE. UU.)
  - Índice del Dólar estadounidense (DXY)
  - Commodities industriales de comparación directa (Cobre / `HG=F`) para aislar la demanda física frente a la prima de refugio puramente narrativa.

------------------------------------------------------------------------

## Datos y Fuentes Textuales [WIP]

- **Corpus Textual:** Fuentes de noticias financieras (Reuters, Bloomberg, Dow Jones), redes sociales (Twitter/X), foros de inversores o transcripciones oficiales de política monetaria *(selección en proceso de filtrado y viabilidad)*.
- **Frecuencia Temporal:** Diaria (con proyección a granularidad intradiaria según disponibilidad de infraestructura y cobertura del corpus).
- **Ventana de Muestreo:** Maximización de cobertura histórica sujeta a la disponibilidad de datos de texto emparejados.

------------------------------------------------------------------------

## Arquitectura del Pipeline: Python -\> R

El flujo de trabajo desacopla la ingeniería de datos del modelado econométrico avanzado para garantizar modularidad y reproducibilidad:

1.  **Fase 1: Extracción y Armonización (Python + `uv`)**
    - Descarga automatizada desde APIs (`yfinance`, FRED vía `pandas-datareader`, y librerías especializadas).
    - Normalización dimensional: conversión de unidades de cotización chinas (RMB por gramo) a estándares occidentales (USD por onza troy) mediante series de tipo de cambio USD/CNY sincrónicas.
    - Manejo de desalineamiento de calendarios bursátiles cruzados (feriados locales de EE. UU., Reino Unido y China).
    - Generación y exportación de matrices limpias a formatos estructurados (`.csv` o `.parquet`) en `data/processed/`.
2.  **Fase 2: Modelado Econométrico e Inferencia (R)**
    - Carga de datos limpios en modo de solo lectura.
    - Pruebas de estacionariedad, quiebres estructurales y cointegración.
    - Estimación de modelos de series de tiempo (ARMAX, familias GARCH) sobre los retornos y residuos no fundamentales.
    - Cruce econométrico con señales extraídas del corpus textual y validación fuera de muestra (*out-of-sample*).

------------------------------------------------------------------------

## Estructura del Repositorio

- `data/`: Datos del proyecto (ignorado por Git, no versionado).
  - `raw/`: Descargas directas e inmutables de las fuentes de origen.
  - `processed/`: Paneles normalizados, sincronizados y listos para modelación.
  - `text/`: Archivos y estructuras del corpus textual [WIP].
- `notebooks/`: Entornos exploratorios `.ipynb` para prototipado rápido y validación visual.
- `src/`: Módulos de Python para ingestión, conversión de unidades y construcción del panel.
- `r_models/`: Scripts de R para estimación econométrica, pruebas de robustez y análisis residual.
- `outputs/`: Resultados exportados automáticamente por el código.
  - `figures/`: Gráficos vectoriales y en alta resolución.
  - `tables/`: Tablas de resultados en formato LaTeX/Markdown.
- `docs/`: Documentación complementaria, bitácoras de trabajo y borradores del documento final.

------------------------------------------------------------------------

## Instalación y Configuración del Entorno

### Requisitos Previos

- Gestor de paquetes de Python: [`uv`](https://github.com/astral-sh/uv)
- R (versión 4.3 o superior)

### Configuración del Entorno de Python

``` bash
# Clonar el repositorio
git clone [https://github.com/jillanes-va/dccs-gold-thesis.git](https://github.com/jillanes-va/dccs-gold-thesis.git)
cd dccs-gold-thesis

# Sincronizar el entorno virtual administrado por uv
uv sync
```

### Ejecución del Pipeline de Datos [WIP]

``` bash
# Comando principal de extracción y procesamiento (en construcción)
# uv run python src/pipeline.py
```

------------------------------------------------------------------------

## Estado Actual del Proyecto

- [x] Revisión de literatura especializada en economía narrativa y microestructura del oro.
- [x] Construcción del pipeline base de armonización bursátil (COMEX, LBMA, SGE, SHFE).
- [ ] Definición y adquisición formal del corpus textual definitivo.
- [ ] Especificación econométrica del modelo de dos etapas en R.
- [ ] Redacción de la propuesta de proyecto de tesis.

------------------------------------------------------------------------

## Licencia

Este proyecto se distribuye bajo la licencia **MIT**. Consulta el archivo `LICENSE` para más detalles.

*Nota: La licencia de código aplica al software y algoritmos desarrollados en este repositorio. Los derechos sobre el texto formal de la tesis, interpretaciones y publicaciones derivadas quedan reservados por el autor y las normativas académicas de la Universidad del Desarrollo hasta su defensa y divulgación oficial.*
