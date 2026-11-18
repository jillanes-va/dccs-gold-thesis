"""Contrato científico-técnico: etiquetas NLI, ausencia de truncado y pesos reales."""
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import torch

from src.infini_models import ModelBank, ModelUnavailable


class Batch(dict):
    def __getattr__(self, name):
        return self[name]

    def to(self, device):
        return self


class Tokenizer:
    def __call__(self, text, other=None, **kwargs):
        if kwargs.get("return_offsets_mapping"):
            return {"offset_mapping": [match.span() for match in re.finditer(r"\S+", text)]}
        if kwargs.get("return_tensors"):
            n = len(text) if isinstance(text, list) else 1
            return Batch(input_ids=torch.ones((n, 5), dtype=torch.long), attention_mask=torch.ones((n, 5)))
        return {"input_ids": list(range(len(text.split()) + 2))}

    def num_special_tokens_to_add(self, pair=False):
        return 2


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.bank = ModelBank(root / "cache", root / "run", local_files_only=True)
        self.bank.tokenizer = Tokenizer()

    def test_restricted_model_does_not_request_credentials_or_network(self):
        with patch("src.infini_models.AutoTokenizer.from_pretrained") as loader:
            with self.assertRaises(ModelUnavailable):
                self.bank.load("fomc")
        loader.assert_not_called()
        self.assertEqual(self.bank.status["fomc"]["status"], "requires_authorized_access")

    def test_long_input_rejected_instead_of_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, "windows"):
            self.bank._inputs(["one two three four"], max_tokens=4)

    def test_windows_preserve_offsets_and_cover_all_tokens(self):
        self.bank.load = Mock(return_value=self.bank)
        text = "one two three four five six seven eight nine ten"
        windows = self.bank.windows("zeroshot_xtremedistil", text, max_tokens=7, overlap=1)
        self.assertEqual([(w["token_start"], w["token_end"]) for w in windows], [(0, 5), (4, 9), (8, 10)])
        for window in windows:
            self.assertEqual(window["text"], text[window["char_start"]:window["char_end"]])
        self.assertEqual(windows[-1]["char_end"], len(text))

    def test_invalid_overlap_rejected(self):
        self.bank.load = Mock(return_value=self.bank)
        with self.assertRaises(ValueError):
            self.bank.windows("zeroshot_xtremedistil", "a b", max_tokens=4, overlap=2)

    def test_nli_entailment_is_read_from_config_not_assumed_last_label(self):
        self.bank.load = Mock(return_value=self.bank)
        self.bank.model = Mock(return_value=SimpleNamespace(logits=torch.tensor([[4., 0.], [0., 4.]])))
        self.bank.model.config = SimpleNamespace(label2id={"entailment": 0, "not_entailment": 1})
        scores = self.bank.zero_shot("zeroshot_xtremedistil", "Example", ["reports a fact", "makes a forecast"])
        self.assertGreater(scores[0]["score"], .98)
        self.assertLess(scores[1]["score"], .02)

    def test_generic_nli_labels_not_guessed(self):
        self.bank.load = Mock(return_value=self.bank)
        self.bank.model = SimpleNamespace(config=SimpleNamespace(label2id={"LABEL_0": 0, "LABEL_1": 1}))
        with self.assertRaisesRegex(ValueError, "no se adivina"):
            self.bank.zero_shot("zeroshot_xtremedistil", "Example", ["reports a fact"])

    def test_untrained_classification_head_rejected(self):
        with patch("src.infini_models.AutoTokenizer.from_pretrained", return_value=Tokenizer()), patch(
            "src.infini_models.AutoModelForSequenceClassification.from_pretrained",
            return_value=(Mock(), {"missing_keys": ["classifier.weight", "classifier.bias"]})
        ):
            with self.assertRaisesRegex(ModelUnavailable, "cabeza aleatoria"):
                self.bank.load("speech_act")
        self.assertEqual(self.bank.status["speech_act"]["status"], "load_failed")
        self.assertIsNone(self.bank.model)

    def test_encoder_not_presented_as_supervised_classifier(self):
        with self.assertRaises(ValueError):
            self.bank.classify("roberta_base", ["A text"])


if __name__ == "__main__":
    unittest.main()
