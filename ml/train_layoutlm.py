"""Fine-tune and evaluate LayoutLMv3 on the versioned synthetic PDF corpus."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pymupdf
import torch
from torch.utils.data import DataLoader, Dataset
from transformers import LayoutLMv3ForTokenClassification, LayoutLMv3Processor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.extraction.layoutlmv3 import (  # noqa: E402
    FIELD_NAMES,
    LABELS,
    LayoutToken,
    read_layout_page,
)

EXTRACTION_REPORT = Path("reports/extraction.json")
ANNOTATIONS_FILE = Path("data/synthetic/documents_v2/annotations.json")
DOCUMENTS_DIR = ANNOTATIONS_FILE.parent
DEFAULT_MODEL = "microsoft/layoutlmv3-base"
DEFAULT_WEIGHTS = Path("ml/weights/layoutlmv3")
LABEL2ID = {label: index for index, label in enumerate(LABELS)}
ID2LABEL = {index: label for label, index in LABEL2ID.items()}


def compute_bbox_iou(
    box1: tuple[int, int, int, int] | dict[str, int],
    box2: tuple[int, int, int, int] | dict[str, int],
) -> float:
    """Compute intersection-over-union for normalized LayoutLM bounding boxes."""
    if isinstance(box1, dict):
        x0_1, y0_1, x1_1, y1_1 = (
            box1["x0"],
            box1["y0"],
            box1["x1"],
            box1["y1"],
        )
    else:
        x0_1, y0_1, x1_1, y1_1 = box1
    if isinstance(box2, dict):
        x0_2, y0_2, x1_2, y1_2 = (
            box2["x0"],
            box2["y0"],
            box2["x1"],
            box2["y1"],
        )
    else:
        x0_2, y0_2, x1_2, y1_2 = box2

    intersection_width = max(0, min(x1_1, x1_2) - max(x0_1, x0_2))
    intersection_height = max(0, min(y1_1, y1_2) - max(y0_1, y0_2))
    intersection = intersection_width * intersection_height
    area1 = max(0, x1_1 - x0_1) * max(0, y1_1 - y0_1)
    area2 = max(0, x1_2 - x0_2) * max(0, y1_2 - y0_2)
    union = area1 + area2 - intersection
    return intersection / union if union else 0.0


def spans_from_tags(tags: list[str]) -> dict[str, list[tuple[int, int]]]:
    """Decode BIO word labels into field spans using inclusive/exclusive indices."""
    spans: dict[str, list[tuple[int, int]]] = {name: [] for name in FIELD_NAMES}
    active_name: str | None = None
    start = 0

    def flush(end: int) -> None:
        if active_name is not None:
            spans[active_name].append((start, end))

    for index, tag in enumerate(tags):
        prefix, separator, field_name = tag.partition("-")
        name = field_name if separator and field_name in spans else None
        if prefix == "B" or (name is not None and name != active_name):
            flush(index)
            active_name = name
            start = index
        elif prefix == "I" and name == active_name:
            continue
        else:
            flush(index)
            active_name = None
    flush(len(tags))
    return spans


def _span_box(tokens: list[LayoutToken], span: tuple[int, int]) -> tuple[int, int, int, int]:
    selected = tokens[span[0] : span[1]]
    return (
        min(token.bbox[0] for token in selected),
        min(token.bbox[1] for token in selected),
        max(token.bbox[2] for token in selected),
        max(token.bbox[3] for token in selected),
    )


def _read_annotations(limit: int | None = None) -> list[dict[str, Any]]:
    if not ANNOTATIONS_FILE.exists():
        raise FileNotFoundError(f"{ANNOTATIONS_FILE} is missing; generate the dataset first")
    annotations = json.loads(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    if not isinstance(annotations, list):
        raise ValueError(f"{ANNOTATIONS_FILE} must contain a list of document annotations")
    return annotations[:limit] if limit is not None else annotations


def _token_labels(
    word_ids: list[int | None],
    word_tags: list[str],
) -> list[int]:
    labels: list[int] = []
    previous_word_id: int | None = None
    for word_id in word_ids:
        if word_id is None or word_id >= len(word_tags):
            labels.append(-100)
            previous_word_id = word_id
            continue
        tag = word_tags[word_id]
        if tag == "O":
            labels.append(LABEL2ID["O"])
        elif word_id != previous_word_id:
            labels.append(LABEL2ID[tag])
        else:
            _, _, field_name = tag.partition("-")
            labels.append(LABEL2ID[f"I-{field_name}"])
        previous_word_id = word_id
    return labels


def _class_weights(examples: list[dict[str, Any]]) -> torch.Tensor:
    """Reduce the dominance of outside tokens without amplifying rare labels excessively."""
    counts = torch.zeros(len(LABELS), dtype=torch.float64)
    for example in examples:
        labels = torch.tensor(example["labels"], dtype=torch.long)
        valid_labels = labels[labels != -100]
        counts += torch.bincount(valid_labels, minlength=len(LABELS)).to(torch.float64)

    present = counts > 0
    if not present.any():
        raise ValueError("Training examples contain no labeled tokens")
    weights = torch.zeros_like(counts)
    weights[present] = torch.sqrt(counts.sum() / (counts[present] * present.sum()))
    weights[present] /= weights[present].mean()
    return weights.clamp(max=5.0).to(torch.float32)


def _build_examples(
    annotations: list[dict[str, Any]],
    processor: LayoutLMv3Processor,
) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for annotation in annotations:
        pdf_path = DOCUMENTS_DIR / str(annotation["filename"])
        if not pdf_path.exists():
            raise FileNotFoundError(f"Annotated PDF is missing: {pdf_path}")
        document = pymupdf.open(str(pdf_path))
        try:
            for page_index in range(len(document)):
                layout = read_layout_page(document[page_index])
                if not layout.tokens:
                    continue
                word_tags = ["O"] * len(layout.tokens)
                page_number = page_index + 1
                for field in annotation["fields"]:
                    if field["page"] != page_number or field["name"] not in FIELD_NAMES:
                        continue
                    x0, y0, x1, y1 = (
                        int(field["bbox"]["x0"]),
                        int(field["bbox"]["y0"]),
                        int(field["bbox"]["x1"]),
                        int(field["bbox"]["y1"]),
                    )
                    matched = [
                        index
                        for index, token in enumerate(layout.tokens)
                        if x0 <= (token.bbox[0] + token.bbox[2]) / 2 <= x1
                        and y0 <= (token.bbox[1] + token.bbox[3]) / 2 <= y1
                    ]
                    for position, word_index in enumerate(matched):
                        prefix = "B" if position == 0 else "I"
                        word_tags[word_index] = f"{prefix}-{field['name']}"

                encoded = processor(
                    images=layout.image,
                    text=[token.text for token in layout.tokens],
                    boxes=[list(token.bbox) for token in layout.tokens],
                    return_tensors="pt",
                    padding="max_length",
                    truncation=True,
                    max_length=512,
                )
                word_ids = encoded.word_ids(batch_index=0)
                model_inputs = {
                    name: value.squeeze(0).cpu()
                    for name, value in encoded.items()
                    if isinstance(value, torch.Tensor)
                }
                examples.append(
                    {
                        "inputs": model_inputs,
                        "labels": _token_labels(word_ids, word_tags),
                        "word_ids": word_ids,
                        "word_tags": word_tags,
                        "tokens": layout.tokens,
                        "doc_id": str(annotation["doc_id"]),
                        "page_number": page_number,
                    }
                )
        finally:
            document.close()
    if not examples:
        raise ValueError("No searchable PDF pages with annotated words were found")
    return examples


class LayoutTokenDataset(Dataset[dict[str, torch.Tensor]]):
    def __init__(self, examples: list[dict[str, Any]]) -> None:
        self.examples = examples

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        example = self.examples[index]
        item = {name: tensor.clone() for name, tensor in example["inputs"].items()}
        item["labels"] = torch.tensor(example["labels"], dtype=torch.long)
        return item


def _predict_word_tags(
    model: LayoutLMv3ForTokenClassification,
    example: dict[str, Any],
    device: torch.device,
) -> list[str]:
    inputs = {
        name: tensor.unsqueeze(0).to(device)
        for name, tensor in example["inputs"].items()
    }
    with torch.inference_mode():
        logits = model(**inputs).logits[0]
        predicted_ids = logits.argmax(dim=-1).cpu().tolist()

    predicted_tags = ["O"] * len(example["word_tags"])
    seen_words: set[int] = set()
    for token_index, word_id in enumerate(example["word_ids"]):
        if word_id is None or word_id in seen_words or word_id >= len(predicted_tags):
            continue
        predicted_tags[word_id] = ID2LABEL[predicted_ids[token_index]]
        seen_words.add(word_id)
    return predicted_tags


def _evaluate(
    model: LayoutLMv3ForTokenClassification,
    examples: list[dict[str, Any]],
    device: torch.device,
) -> dict[str, Any]:
    metrics: dict[str, dict[str, Any]] = {
        name: {"tp": 0, "fp": 0, "fn": 0, "ious": []} for name in FIELD_NAMES
    }
    for example in examples:
        predicted_tags = _predict_word_tags(model, example, device)
        expected_spans = spans_from_tags(example["word_tags"])
        predicted_spans = spans_from_tags(predicted_tags)
        tokens = example["tokens"]
        for field_name in FIELD_NAMES:
            expected = expected_spans[field_name]
            predicted = predicted_spans[field_name]
            expected_set = set(expected)
            predicted_set = set(predicted)
            metrics[field_name]["tp"] += len(expected_set & predicted_set)
            metrics[field_name]["fp"] += len(predicted_set - expected_set)
            metrics[field_name]["fn"] += len(expected_set - predicted_set)
            predicted_boxes = [_span_box(tokens, span) for span in predicted]
            for expected_span in expected:
                expected_box = _span_box(tokens, expected_span)
                overlap = max(
                    (
                        compute_bbox_iou(expected_box, predicted_box)
                        for predicted_box in predicted_boxes
                    ),
                    default=0.0,
                )
                metrics[field_name]["ious"].append(overlap)

    per_field: dict[str, dict[str, Any]] = {}
    all_ious: list[float] = []
    f1_scores: list[float] = []
    for field_name, values in metrics.items():
        tp, fp, fn = values["tp"], values["fp"], values["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        ious = values["ious"]
        mean_iou = sum(ious) / len(ious) if ious else None
        f1_scores.append(f1)
        all_ious.extend(ious)
        per_field[field_name] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "mean_bbox_iou": round(mean_iou, 4) if mean_iou is not None else None,
            "support": tp + fn,
        }

    macro_f1 = sum(f1_scores) / len(f1_scores)
    overall_iou = sum(all_ious) / len(all_ious) if all_ious else None
    return {
        "macro_f1": round(macro_f1, 4),
        "overall_mean_bbox_iou": round(overall_iou, 4) if overall_iou is not None else None,
        "per_field_metrics": per_field,
    }


def run_extraction_evaluation(
    model: LayoutLMv3ForTokenClassification,
    processor: LayoutLMv3Processor,
    annotations: list[dict[str, Any]],
    training_documents: int,
    device: torch.device,
    report_path: Path,
) -> dict[str, Any]:
    """Report exact BIO-span F1 and measured bbox IoU on a held-out document split."""
    examples = _build_examples(annotations, processor)
    evaluation = _evaluate(model, examples, device)
    macro_f1 = evaluation["macro_f1"]
    mean_iou = evaluation["overall_mean_bbox_iou"]
    payload = {
        "evaluation_name": "Held-out LayoutLMv3 Token Classification Evaluation",
        "model_architecture": "LayoutLMv3 token classification (fine-tuned)",
        "pretrained_model": str(model.config._name_or_path),
        "training_documents": training_documents,
        "held_out_documents_evaluated": len({example["doc_id"] for example in examples}),
        "held_out_pages_evaluated": len(examples),
        "metric_method": "exact BIO word-span F1 and bbox IoU against annotated word boxes",
        "training_loss": "inverse-square-root token-frequency weighted cross-entropy, capped at 5x",
        **evaluation,
        "is_gate_passed": bool(
            mean_iou is not None and macro_f1 >= 0.85 and mean_iou >= 0.25
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"LayoutLMv3 held-out results: macro F1={macro_f1:.4f}, "
        f"mean bbox IoU={mean_iou if mean_iou is not None else 'not measured'}"
    )
    print(f"Report written to: {report_path}")
    return payload


def train(args: argparse.Namespace) -> dict[str, Any]:
    if args.epochs < 1:
        raise ValueError("--epochs must be at least 1")
    annotations = _read_annotations(args.max_docs)
    train_annotations = [
        annotation for index, annotation in enumerate(annotations) if index % 5 != 0
    ]
    held_out_annotations = [
        annotation for index, annotation in enumerate(annotations) if index % 5 == 0
    ]
    if not train_annotations or not held_out_annotations:
        raise ValueError("The document set must contain both training and held-out examples")

    torch.manual_seed(42)
    processor = LayoutLMv3Processor.from_pretrained(args.model_name, apply_ocr=False)
    train_examples = _build_examples(train_annotations, processor)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LayoutLMv3ForTokenClassification.from_pretrained(
        args.model_name,
        num_labels=len(LABELS),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        ignore_mismatched_sizes=True,
    ).to(device)
    generator = torch.Generator().manual_seed(42)
    loader = DataLoader(
        LayoutTokenDataset(train_examples),
        batch_size=1,
        shuffle=True,
        generator=generator,
        num_workers=0,
    )
    class_weights = _class_weights(train_examples).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    model.train()
    for epoch in range(args.epochs):
        total_loss = 0.0
        for batch_index, batch in enumerate(loader, start=1):
            batch = {name: tensor.to(device) for name, tensor in batch.items()}
            labels = batch.pop("labels")
            optimizer.zero_grad(set_to_none=True)
            logits = model(**batch).logits
            loss = torch.nn.functional.cross_entropy(
                logits.view(-1, len(LABELS)),
                labels.view(-1),
                weight=class_weights,
                ignore_index=-100,
            )
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu())
            if batch_index % 20 == 0:
                print(f"epoch={epoch + 1} pages={batch_index}/{len(loader)}")
        print(f"epoch={epoch + 1} mean_loss={total_loss / len(loader):.6f}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output_dir, safe_serialization=True)
    processor.save_pretrained(args.output_dir)
    model.eval()
    result = run_extraction_evaluation(
        model,
        processor,
        held_out_annotations,
        len(train_annotations),
        device,
        args.report_path,
    )
    result["training_pages"] = len(train_examples)
    result["training_epochs"] = args.epochs
    result["training_model"] = args.model_name
    args.report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        f"Fine-tuned on {len(train_annotations)} documents / {len(train_examples)} pages; "
        f"held out {result['held_out_documents_evaluated']} documents / "
        f"{result['held_out_pages_evaluated']} pages."
    )
    return result


def evaluate_saved_model(args: argparse.Namespace) -> dict[str, Any]:
    if not (args.output_dir / "config.json").exists():
        raise FileNotFoundError(
            f"Fine-tuned model not found at {args.output_dir}; run with --train first"
        )
    annotations = _read_annotations(args.max_docs)
    held_out_annotations = [
        annotation for index, annotation in enumerate(annotations) if index % 5 == 0
    ]
    processor = LayoutLMv3Processor.from_pretrained(
        args.output_dir,
        apply_ocr=False,
        local_files_only=True,
    )
    model = LayoutLMv3ForTokenClassification.from_pretrained(
        args.output_dir,
        local_files_only=True,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()
    return run_extraction_evaluation(
        model,
        processor,
        held_out_annotations,
        training_documents=0,
        device=device,
        report_path=args.report_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune or evaluate LayoutLMv3.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--train", action="store_true", help="Fine-tune the pretrained model")
    mode.add_argument("--eval-only", action="store_true", help="Evaluate saved local weights")
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--report-path", type=Path, default=EXTRACTION_REPORT)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--max-docs", type=int)
    args = parser.parse_args()
    if args.max_docs is not None and args.max_docs < 5:
        parser.error("--max-docs must be at least 5 to retain a held-out split")
    if args.train:
        train(args)
    else:
        evaluate_saved_model(args)


if __name__ == "__main__":
    main()
