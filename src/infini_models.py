"""Cargas y ejemplos exploratorios del PDF, sin definir índices científicos."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import gc
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform

import torch
from huggingface_hub import hf_hub_download
from transformers import (AutoModel, AutoModelForCausalLM, AutoModelForSeq2SeqLM, BertConfig,
                          AutoModelForSequenceClassification, AutoTokenizer)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo_id: str
    revision: str
    kind: str
    pdf_pages: str
    note: str
    gated: bool = False


# Revisiones consultadas el 2026-11-18. Los modelos base son elecciones técnicas
# de tamaño representativo cuando el PDF solo nombra una familia.
SPECS = [
    ModelSpec("speech_act", "quantor-project/speech-act-classification", "27b8c58b65139fe7b9e1a1771062581a9d35a415",
              "classification", "1,3,10,15-16", "Actos de habla. Tarjeta incompleta; no inventar significados para LABEL_n."),
    ModelSpec("zeroshot_deberta", "MoritzLaurer/deberta-v3-xsmall-zeroshot-v1.1-all-33", "262ae02f29173eec1c250f90804dc7edc677dcff",
              "zero_shot", "2,10", "NLI en inglés; etiquetas de ejemplo exploratorias, no taxonomía aprobada."),
    ModelSpec("zeroshot_xtremedistil", "MoritzLaurer/xtremedistil-l6-h256-zeroshot-v1.1-all-33", "c07f66d9cbf781191bee66edfe8ad7856f045781",
              "zero_shot", "2,10", "NLI pequeño en inglés; mismas etiquetas para comparar ejemplos."),
    ModelSpec("causal_news", "tanfiona/cnc-v2-st1-csc", "2d036aaff58d971bcc2599465a956d512294c90a",
              "classification", "8,15", "Baseline oficial CNC V2; no equivale al modelo V1 ni a extracción de spans."),
    ModelSpec("roberta_base", "FacebookAI/roberta-base", "e2da8e2f811d1448a5b465c236feacd80ffbac7b",
              "encoder", "3,9-10,15", "Encoder base sin cabeza entrenada para las tareas del PDF."),
    ModelSpec("roberta_large", "FacebookAI/roberta-large", "722cf37b1afa9454edce342e7895e588b6ff1d59",
              "encoder", "12", "Base RoBERTa-large; no es el ajuste FOMC."),
    ModelSpec("deberta_base", "microsoft/deberta-v3-base", "8ccc9b6f36199bec6961081d44eb72fb3f7353f3",
              "encoder", "9-10,13", "Encoder base propuesto para fine-tuning; no mide actos por sí solo."),
    ModelSpec("bert_base", "google-bert/bert-base-uncased", "86b5e0934494bd15c9632b12f734a8a67f723594",
              "encoder", "7,9", "BERT representativo; no sustituye los pesos del estudio MPQA/CommitmentBank."),
    ModelSpec("electra_base", "google/electra-base-discriminator", "1ae76a97c7e84a4e640876a07453fccd636f0667",
              "encoder", "9", "Variante inglesa de ELECTRA; SELECTRA del PDF es español y se excluye."),
    ModelSpec("t5_base", "google-t5/t5-base", "a9723ea7f1b39c1eae772870f3b547bf6ef7e6c1",
              "seq2seq", "7", "T5 base; el ejemplo de resumen no reproduce las cabezas MPQA."),
    ModelSpec("fomc", "gtfintechlab/FOMC-RoBERTa", "1c0e40cc6f364fe60f92482ffa496f65647f4a34",
              "classification", "2,12-13", "Acceso manual del autor; admite un checkpoint local autorizado.", True),
    ModelSpec("llama31_8b", "meta-llama/Llama-3.1-8B", "d04e592bb4f6aa9cfee91e2e20afa771667e1d4b",
              "causal_lm", "9", "Base de acceso restringido; no es el fine-tune de Causal Micro-Narratives.", True),
]
MODELS = {spec.name: spec for spec in SPECS}
PUBLIC_MODELS = [spec.name for spec in SPECS if not spec.gated]
EXAMPLES = ["The central bank expects inflation to decline next year.",
            "Higher borrowing costs caused investment to fall.",
            "Officials said they would keep interest rates unchanged."]
DEMO_LABELS = ["reports a fact", "makes a forecast", "expresses a warning", "makes a commitment"]
LABEL_ALIASES = {
    "causal_news": {"LABEL_0": "Non-causal", "LABEL_1": "Causal", "0": "Non-causal", "1": "Causal"},
    "fomc": {"LABEL_0": "Dovish", "LABEL_1": "Hawkish", "LABEL_2": "Neutral"},
}


class ModelUnavailable(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


class ModelBank:
    """Un modelo residente a la vez; caché de pesos persistente y revisiones fijas."""

    def __init__(self, cache_dir, run_dir, *, device="cpu", local_files_only=False, local_overrides=None):
        self.cache_dir, self.run_dir = Path(cache_dir), Path(run_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.device = torch.device(device)
        self.local_files_only = local_files_only
        self.local_overrides = local_overrides or {}
        self.active_name, self.tokenizer, self.model = None, None, None
        self.status = {}
        self.manifest = {"started_at_utc": utc_now(), "device": str(self.device), "python": platform.python_version(),
                         "platform": platform.platform(), "torch": torch.__version__,
                         "cuda_available": torch.cuda.is_available(),
                         "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                         "threads": torch.get_num_threads(), "local_files_only": local_files_only,
                         "packages": {p: version(p) for p in ["transformers", "huggingface-hub", "sentencepiece"]},
                         "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         "specs": [asdict(s) for s in SPECS], "status": self.status}
        self._persist()

    def _persist(self):
        write_json(self.run_dir / "models_manifest.json", self.manifest)

    def release(self):
        self.model = self.tokenizer = self.active_name = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def load(self, name):
        if self.active_name == name:
            return self
        spec = MODELS[name]
        self.release()
        override = self.local_overrides.get(name)
        if spec.gated and not override:
            self.status[name] = {"status": "requires_authorized_access", "at_utc": utc_now(), "repo_id": spec.repo_id}
            self._persist()
            raise ModelUnavailable(f"{spec.repo_id}: se requiere acceso del autor o local_overrides['{name}']")
        source = str(Path(override).resolve()) if override else spec.repo_id
        kwargs = dict(cache_dir=str(self.cache_dir), local_files_only=True if override else self.local_files_only,
                      trust_remote_code=False, token=False)
        if not override:
            kwargs["revision"] = spec.revision
        try:
            config_kwargs = {}
            compatibility = None
            if name == "causal_news":
                config_path = Path(source) / "config.json" if override else Path(hf_hub_download(
                    spec.repo_id, "config.json", revision=spec.revision, cache_dir=str(self.cache_dir),
                    local_files_only=self.local_files_only, token=False))
                raw_config = json.loads(config_path.read_text(encoding="utf-8"))
                original_labels = raw_config.get("id2label")
                # Este checkpoint de Transformers 4 guardó labels como enteros.
                # Transformers 5 exige strings. No se cambia el orden ni los pesos.
                raw_config["id2label"] = {key: str(value) for key, value in original_labels.items()}
                config_kwargs["config"] = BertConfig.from_dict(raw_config)
                compatibility = {"change": "id2label values converted int to str in memory",
                                 "original_id2label": original_labels, "cached_files_modified": False}
            tokenizer = AutoTokenizer.from_pretrained(source, **config_kwargs, **kwargs)
            factory = {"classification": AutoModelForSequenceClassification, "zero_shot": AutoModelForSequenceClassification,
                       "encoder": AutoModel, "seq2seq": AutoModelForSeq2SeqLM, "causal_lm": AutoModelForCausalLM}[spec.kind]
            model, info = factory.from_pretrained(source, output_loading_info=True, **config_kwargs, **kwargs)
            # Un clasificador con una cabeza recién inicializada no es un modelo de la tarea.
            missing = sorted(info.get("missing_keys", []))
            meaningful_missing = [key for key in missing if not (spec.kind == "encoder" and "pooler" in key)]
            if meaningful_missing:
                raise ModelUnavailable(f"Pesos ausentes: {meaningful_missing}; no se usará una cabeza aleatoria")
            model.to(self.device).eval()
            self.model, self.tokenizer, self.active_name = model, tokenizer, name
            self.status[name] = {"status": "loaded", "at_utc": utc_now(), "repo_id": spec.repo_id,
                                 "revision": spec.revision if not override else "local_override",
                                 "local_path": source if override else None,
                                 "config_sha256": hashlib.sha256(model.config.to_json_string().encode()).hexdigest(),
                                 "parameters": sum(p.numel() for p in model.parameters()),
                                 "id2label": model.config.id2label,
                                 "unused_pooler_missing_keys": missing, "config_compatibility": compatibility, "note": spec.note}
            self._persist()
            return self
        except Exception as exc:
            self.release()
            self.status[name] = {"status": "load_failed", "at_utc": utc_now(), "error_type": type(exc).__name__,
                                 "error": str(exc)[:1200], "repo_id": spec.repo_id, "revision": spec.revision}
            self._persist()
            raise

    def _inputs(self, texts, max_tokens=256):
        if not texts or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ValueError("Se requieren textos no vacíos")
        lengths = [len(self.tokenizer(text, truncation=False)["input_ids"]) for text in texts]
        if max(lengths) > max_tokens:
            raise ValueError(f"Longitudes {lengths} exceden {max_tokens}; usa windows() para conservar los segmentos")
        return self.tokenizer(texts, padding=True, truncation=False, return_tensors="pt").to(self.device)

    def classify(self, name, texts, max_tokens=256):
        if MODELS[name].kind != "classification":
            raise ValueError("classify requiere un modelo supervisado de clasificación")
        self.load(name)
        inputs = self._inputs(texts, max_tokens)
        with torch.inference_mode():
            logits = self.model(**inputs).logits
            if getattr(self.model.config, "problem_type", None) == "multi_label_classification":
                raise ValueError("Este ejemplo usa softmax; el checkpoint declara multi-label")
            scores = logits.softmax(-1).cpu().tolist()
        return [{"text": text, "scores": [{"label": self.model.config.id2label.get(i, str(i)),
                    "label_description": LABEL_ALIASES.get(name, {}).get(self.model.config.id2label.get(i, str(i))),
                    "score": score} for i, score in enumerate(row)]} for text, row in zip(texts, scores)]

    def zero_shot(self, name, text, labels, template="This sentence {}.", max_tokens=512):
        if MODELS[name].kind != "zero_shot":
            raise ValueError("zero_shot requiere un checkpoint NLI adaptado")
        if not text.strip() or not labels or len(set(labels)) != len(labels) or "{}" not in template:
            raise ValueError("Texto y etiquetas deben ser válidos; la plantilla debe contener {}")
        self.load(name)
        label2id = {str(k).lower(): int(v) for k, v in self.model.config.label2id.items()}
        entailment = label2id.get("entailment")
        opposite = label2id.get("contradiction", label2id.get("not_entailment"))
        if entailment is None or opposite is None:
            raise ValueError(f"Etiquetas NLI no interpretables: {label2id}; no se adivina su orden")
        hypotheses = [template.format(label) for label in labels]
        pairs = self.tokenizer([text] * len(labels), hypotheses, padding=True, truncation=False, return_tensors="pt")
        if pairs.input_ids.shape[1] > max_tokens:
            raise ValueError("El par NLI excede el límite; usar un segmento más corto con windows()")
        with torch.inference_mode():
            logits = self.model(**pairs.to(self.device)).logits
            # Cada etiqueta se evalúa independientemente (multi_label=True en la pipeline HF).
            scores = logits[:, [opposite, entailment]].softmax(-1)[:, 1].cpu().tolist()
        return [{"label": label, "score": score, "hypothesis": hypothesis} for label, score, hypothesis in
                zip(labels, scores, hypotheses)]

    def embed(self, name, texts, max_tokens=256):
        if MODELS[name].kind != "encoder":
            raise ValueError("embed requiere un encoder base")
        self.load(name)
        inputs = self._inputs(texts, max_tokens)
        with torch.inference_mode():
            hidden = self.model(**inputs).last_hidden_state
            mask = inputs.attention_mask.unsqueeze(-1)
            vectors = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
        return vectors.cpu()

    def generate(self, name, texts, max_tokens=256, max_new_tokens=48):
        if MODELS[name].kind not in {"seq2seq", "causal_lm"}:
            raise ValueError("generate requiere un modelo generativo")
        self.load(name)
        inputs = self._inputs(texts, max_tokens)
        with torch.inference_mode():
            result = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        if MODELS[name].kind == "causal_lm":
            result = result[:, inputs.input_ids.shape[1]:]
        return self.tokenizer.batch_decode(result, skip_special_tokens=True)

    def windows(self, name, text, max_tokens=192, overlap=24):
        """Ventanas técnicas con offsets; no las presenta como cláusulas lingüísticas."""
        self.load(name)
        if not isinstance(text, str) or not text.strip():
            return []
        size = max_tokens - self.tokenizer.num_special_tokens_to_add(pair=False)
        if size <= 0 or not 0 <= overlap < size:
            raise ValueError("Tamaño/solapamiento de ventanas inválido")
        encoding = self.tokenizer(text, add_special_tokens=False, truncation=False, return_offsets_mapping=True)
        offsets = encoding["offset_mapping"]
        windows = []
        for start in range(0, len(offsets), size - overlap):
            end = min(start + size, len(offsets))
            left, right = offsets[start][0], offsets[end - 1][1]
            windows.append({"window_index": len(windows), "token_start": start, "token_end": end,
                            "char_start": left, "char_end": right, "text": text[left:right],
                            "overlap_tokens": overlap})
            if end == len(offsets):
                break
        return windows

    def smoke_all(self, names=None):
        """Carga y prueba cada modelo secuencialmente sobre texto sintético, sin noticias remotas."""
        reports = []
        for name in names or PUBLIC_MODELS:
            print(f"Cargando/probando {name} ...", flush=True)
            try:
                kind = MODELS[name].kind
                if kind == "classification":
                    result = self.classify(name, EXAMPLES[:1])
                elif kind == "zero_shot":
                    result = self.zero_shot(name, EXAMPLES[0], DEMO_LABELS[:2])
                elif kind == "encoder":
                    vectors = self.embed(name, EXAMPLES[:1])
                    result = {"shape": list(vectors.shape), "finite": bool(torch.isfinite(vectors).all())}
                else:
                    result = self.generate(name, ["summarize: " + " ".join(EXAMPLES)], max_new_tokens=24)
                record = {"name": name, "status": "passed", "example_result": result}
            except Exception as exc:
                record = {"name": name, "status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:1200]}
            reports.append(record)
            write_json(self.run_dir / "smoke_results.json", reports)
            self.release()
            print(f"{name}: {record['status']}", flush=True)
        return reports
