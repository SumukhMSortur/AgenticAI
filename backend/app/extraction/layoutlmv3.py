"""LayoutLMv3 token-classification inference with an explicit heuristic fallback."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from backend.app.core.config import settings
from backend.app.core.logging import get_logger
from backend.app.domain.models import BBox, ExtractedField
from backend.app.extraction.base import Extractor
from backend.app.extraction.heuristic import HeuristicExtractor

logger = get_logger(__name__)

FIELD_NAMES = (
    "certificate_type",
    "issuer",
    "valid_from",
    "valid_to",
    "scope_materials",
    "facility_id",
    "supplier_id",
)
LABELS = ["O"] + [f"{prefix}-{name}" for name in FIELD_NAMES for prefix in ("B", "I")]


@dataclass(frozen=True)
class LayoutToken:
    text: str
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class LayoutPage:
    image: Image.Image
    tokens: list[LayoutToken]


def read_layout_page(page: Any) -> LayoutPage:
    """Extract searchable words, normalized boxes, and a rendered page image."""
    width = float(page.rect.width or 595)
    height = float(page.rect.height or 842)
    tokens: list[LayoutToken] = []
    for word in page.get_text("words"):
        x0, y0, x1, y1, text = word[:5]
        if not text.strip():
            continue
        bbox = (
            max(0, min(1000, int(round(float(x0) * 1000 / width)))),
            max(0, min(1000, int(round(float(y0) * 1000 / height)))),
            max(0, min(1000, int(round(float(x1) * 1000 / width)))),
            max(0, min(1000, int(round(float(y1) * 1000 / height)))),
        )
        tokens.append(LayoutToken(text=str(text), bbox=bbox))

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    return LayoutPage(image=image, tokens=tokens)


def decode_layout_tokens(
    tags: list[str],
    confidences: list[float],
    tokens: list[LayoutToken],
    doc_id: str,
    doc_hash: str,
    page_number: int,
) -> list[ExtractedField]:
    """Turn BIO token predictions into evidence-linked field spans."""
    fields: list[ExtractedField] = []
    active_name: str | None = None
    active_indices: list[int] = []

    def flush() -> None:
        if active_name is None or not active_indices:
            return
        selected = [tokens[index] for index in active_indices]
        x0 = min(token.bbox[0] for token in selected)
        y0 = min(token.bbox[1] for token in selected)
        x1 = max(token.bbox[2] for token in selected)
        y1 = max(token.bbox[3] for token in selected)
        fields.append(
            ExtractedField(
                name=active_name,
                value=" ".join(token.text for token in selected),
                doc_id=doc_id,
                doc_hash=doc_hash,
                page=page_number,
                bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
                confidence=sum(confidences[index] for index in active_indices)
                / len(active_indices),
            )
        )

    for index, tag in enumerate(tags[: len(tokens)]):
        prefix, separator, field_name = tag.partition("-")
        predicted_name = field_name if separator and prefix in {"B", "I"} else None
        if prefix == "B" or predicted_name != active_name:
            flush()
            active_name = predicted_name
            active_indices = [index] if predicted_name is not None else []
        elif predicted_name is not None:
            active_indices.append(index)
        elif active_name is not None:
            flush()
            active_name = None
            active_indices = []
    flush()
    return fields


class LayoutLMv3Extractor(Extractor):
    """Run a fine-tuned LayoutLMv3 token classifier when local weights exist."""

    def __init__(self, weights_path: Path | str | None = None) -> None:
        self.weights_path = Path(
            weights_path or settings.LAYOUTLM_WEIGHTS_PATH or "ml/weights/layoutlmv3"
        )
        self.heuristic = HeuristicExtractor()
        self.model: Any = None
        self.processor: Any = None
        self.id2label = dict(enumerate(LABELS))
        self.model_loaded = False

        model_files = ("model.safetensors", "pytorch_model.bin")
        if (self.weights_path / "config.json").exists() and any(
            (self.weights_path / filename).exists() for filename in model_files
        ):
            try:
                from transformers import LayoutLMv3ForTokenClassification, LayoutLMv3Processor

                self.processor = LayoutLMv3Processor.from_pretrained(
                    self.weights_path,
                    apply_ocr=False,
                    local_files_only=True,
                )
                self.model = LayoutLMv3ForTokenClassification.from_pretrained(
                    self.weights_path,
                    local_files_only=True,
                )
                self.model.eval()
                self.id2label = {
                    int(index): str(label)
                    for index, label in self.model.config.id2label.items()
                }
                self.model_loaded = True
                logger.info("Loaded fine-tuned LayoutLMv3 weights from %s", self.weights_path)
            except (ImportError, OSError, RuntimeError, ValueError) as error:
                logger.warning(
                    "Unable to load LayoutLMv3 weights from %s; using heuristic extraction: %s",
                    self.weights_path,
                    error,
                )
        else:
            logger.info(
                "Fine-tuned LayoutLMv3 weights not found at %s; using heuristic extraction",
                self.weights_path,
            )

    def extract(self, doc_path: Path, doc_id: str, doc_hash: str) -> list[ExtractedField]:
        if not self.model_loaded or self.model is None or self.processor is None:
            return self.heuristic.extract(doc_path, doc_id, doc_hash)

        import torch

        document = pymupdf.open(str(doc_path))
        extracted: list[ExtractedField] = []
        try:
            device = next(self.model.parameters()).device
            for page_index in range(len(document)):
                layout = read_layout_page(document[page_index])
                if not layout.tokens:
                    continue
                encoded = self.processor(
                    images=layout.image,
                    text=[token.text for token in layout.tokens],
                    boxes=[list(token.bbox) for token in layout.tokens],
                    return_tensors="pt",
                    truncation=True,
                    max_length=512,
                )
                word_ids = encoded.word_ids(batch_index=0)
                model_inputs = {
                    name: value.to(device) for name, value in encoded.items() if hasattr(value, "to")
                }
                with torch.inference_mode():
                    logits = self.model(**model_inputs).logits[0]
                    probabilities = torch.softmax(logits, dim=-1)
                    predicted_ids = logits.argmax(dim=-1).tolist()
                    token_confidences = probabilities.max(dim=-1).values.tolist()

                word_tags = ["O"] * len(layout.tokens)
                word_confidences = [0.0] * len(layout.tokens)
                seen_words: set[int] = set()
                for token_index, word_id in enumerate(word_ids):
                    if word_id is None or word_id in seen_words or word_id >= len(layout.tokens):
                        continue
                    seen_words.add(word_id)
                    word_tags[word_id] = self.id2label.get(predicted_ids[token_index], "O")
                    word_confidences[word_id] = float(token_confidences[token_index])
                extracted.extend(
                    decode_layout_tokens(
                        word_tags,
                        word_confidences,
                        layout.tokens,
                        doc_id,
                        doc_hash,
                        page_index + 1,
                    )
                )
        finally:
            document.close()
        return extracted


def get_extractor() -> Extractor:
    """Factory returning the configured extractor."""
    return LayoutLMv3Extractor()
