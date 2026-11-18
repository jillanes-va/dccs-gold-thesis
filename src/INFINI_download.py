
#!/usr/bin/env python3
# infini_2025_eng.py
# Instalar: pip install -U datasets pyarrow

import argparse
import gzip
import json
from pathlib import Path
from datasets import load_dataset

DATASET = "ruggsea/infini-news-corpus"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "INFINI_dataset"


def main():
    parser = argparse.ArgumentParser(
        description="Descarga noticias en inglés capturadas en 2025."
    )
    parser.add_argument(
        "--max-articles", type=int, default=10000,
        help="Máximo de artículos; 0 = sin límite."
    )
    parser.add_argument(
        "--min-chars", type=int, default=0,
        help="Longitud mínima del cuerpo."
    )
    parser.add_argument(
        "--strict-date", action="store_true",
        help="Exigir también publish_date de 2025."
    )
    parser.add_argument(
        "--output", default="infini_2025_eng.jsonl.gz",
        help="Nombre del archivo dentro de data/INFINI_dataset/."
    )
    args = parser.parse_args()

    if args.max_articles < 0:
        parser.error("--max-articles no puede ser negativo")

    if Path(args.output).name != args.output:
        parser.error("--output debe ser un nombre de archivo, sin directorios")

    output = OUTPUT_DIR / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    # Acceso remoto progresivo a los archivos de 2025.
    # No descarga los 1,67 TB del repositorio.
    ds = load_dataset(
        DATASET,
        "year_2025",
        split="train",
        streaming=True
    )

    # Evita problemas de conversión del hash uint64.
    ds = ds.remove_columns(["text_xxhash64"])

    saved = 0
    scanned = 0

    with gzip.open(output, "wt", encoding="utf-8") as f:
        for row in ds:
            scanned += 1

            if row.get("language_iso639_3") != "eng":
                continue

            body = row.get("text") or ""
            if len(body) < args.min_chars:
                continue

            publication_date = row.get("publish_date") or ""
            if args.strict_date and not str(
                publication_date
            ).startswith("2025"):
                continue

            article = {
                "title": row.get("title"),
                "text": body,
                "publish_date": publication_date,
                "warc_date": str(row.get("warc_date")),
                "url": row.get("url"),
                "source": row.get("url_hostname"),
                "author": row.get("author"),
                "warc_record_id": row.get("warc_record_id"),
                "language": "eng",
            }

            f.write(
                json.dumps(article, ensure_ascii=False) + "\n"
            )
            saved += 1

            if saved % 1000 == 0:
                print(
                    f"Guardados: {saved:,} | "
                    f"Revisados: {scanned:,}",
                    flush=True
                )

            if args.max_articles and saved >= args.max_articles:
                break

    print(f"\nFinalizado: {saved:,} artículos")
    print(f"Archivo: {output.resolve()}")


if __name__ == "__main__":
    main()
