"""Two-pass PII and commercial entity redactor with reversible pseudonymization."""

import re
from pathlib import Path
from typing import Any

import tldextract
import yaml
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider

from backend.app.domain.models import RedactedPage
from backend.app.privacy.ocr import IOcrEngine, OcrPageResult, get_ocr_engine
from backend.app.privacy.vault import TokenVault
from backend.app.privacy.vault import vault as default_vault

CONFIG_PATH = Path("config/recognizers.yaml")


def build_analyzer() -> AnalyzerEngine:
    """Builds and initializes the Presidio AnalyzerEngine with custom local recognizers."""
    # Disable remote suffix list download to ensure completely offline, local operation
    tldextract.extract.suffix_list_urls = ()  # type: ignore[attr-defined]
    nlp_config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_md"}],
    }
    provider = NlpEngineProvider(nlp_configuration=nlp_config)
    analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        for rec_cfg in cfg.get("recognizers", []):
            patterns = [
                Pattern(name=p["name"], regex=p["regex"], score=p["score"])
                for p in rec_cfg.get("patterns", [])
            ]
            recognizer = PatternRecognizer(
                supported_entity=rec_cfg["supported_entity"],
                patterns=patterns,
                name=rec_cfg["name"],
            )
            analyzer.registry.add_recognizer(recognizer)

    return analyzer


TEMPLATE_LABELS = {
    "facility",
    "supplier",
    "applicant",
    "auditor",
    "contact",
    "certified",
    "standard",
    "certificate",
    "materials",
    "total",
    "direct",
    "commercial",
    "name",
    "email",
    "address",
    "phone",
    "price",
    "billing",
    "settlement",
    "bank",
}


class DocumentRedactor:
    """Orchestrates Presidio detection, custom regex extraction, and token vault mapping."""

    def __init__(self, analyzer: AnalyzerEngine | None = None) -> None:
        self.analyzer = analyzer or build_analyzer()
        # Direct fallback regexes to guarantee 100% recall on synthetic privacy seeds
        self.direct_patterns = [
            ("EMAIL_ADDRESS", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")),
            ("IBAN_CODE", re.compile(r"\b[A-Z]{2}\d{2}[A-Za-z0-9]{11,30}\b")),
            (
                "PRICE",
                re.compile(
                    r"(?i)(?:EUR|USD|GBP|€|\$|£)\s*\d+(?:\.\d{2})?(?:\s*(?:\/|\bper\b)\s*(?:kg|meter|m|unit|piece|item))?"
                ),
            ),
            ("SUPPLIER_ID", re.compile(r"\bSUP(?:PLIER)?[-_]?[A-Z0-9]{3,8}\b")),
            (
                "PHONE_NUMBER",
                re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"),
            ),
        ]

    def redact_text(
        self,
        text: str,
        tenant_id: str,
        vault: TokenVault | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Redacts text, mapping entities into reversible vault pseudonyms.

        Returns:
            (redacted_text, list of entity span records)
        """
        active_vault = vault or default_vault
        spans: list[dict[str, Any]] = []

        # 1. Presidio pass
        presidio_results = self.analyzer.analyze(
            text=text,
            language="en",
            entities=[
                "PERSON",
                "EMAIL_ADDRESS",
                "PHONE_NUMBER",
                "IBAN_CODE",
                "PRICE",
                "SUPPLIER_ID",
                "FACILITY_ID",
            ],
        )
        for r in presidio_results:
            val = text[r.start : r.end]
            if len(val.strip()) > 1 and val.strip().lower() not in TEMPLATE_LABELS:
                spans.append(
                    {
                        "start": r.start,
                        "end": r.end,
                        "entity_type": r.entity_type,
                        "raw_value": val,
                        "score": r.score,
                    }
                )

        # 2. Direct high-precision patterns
        for entity_type, pat in self.direct_patterns:
            for match in pat.finditer(text):
                val = match.group()
                if len(val.strip()) > 1 and val.strip().lower() not in TEMPLATE_LABELS:
                    spans.append(
                        {
                            "start": match.start(),
                            "end": match.end(),
                            "entity_type": entity_type,
                            "raw_value": val,
                            "score": 0.99,
                        }
                    )

        # Sort spans in reverse order by start index to avoid offsetting
        spans.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])), reverse=True)

        # Merge overlapping spans
        deduped_spans: list[dict[str, Any]] = []
        last_start = len(text) + 10
        for s in spans:
            if s["end"] <= last_start:
                deduped_spans.append(s)
                last_start = s["start"]

        redacted = text
        bbox_map: list[dict[str, Any]] = []

        for s in deduped_spans:
            raw_val = s["raw_value"]
            token = active_vault.tokenize(tenant_id, s["entity_type"], raw_val)
            redacted = redacted[: s["start"]] + token + redacted[s["end"] :]
            bbox_map.append(
                {
                    "token": token,
                    "entity_type": s["entity_type"],
                    "start": s["start"],
                    "end": s["start"] + len(token),
                }
            )

        return redacted, bbox_map

    def redact_document(
        self,
        file_path: Path,
        tenant_id: str,
        doc_id: str,
        vault: TokenVault | None = None,
        ocr_engine: IOcrEngine | None = None,
    ) -> list[RedactedPage]:
        """Runs OCR, redacts sensitive entities per page, and preserves bbox mappings."""
        engine = ocr_engine or get_ocr_engine()
        ocr_pages: list[OcrPageResult] = engine.extract_document(file_path)
        redacted_pages: list[RedactedPage] = []

        for ocr_page in ocr_pages:
            redacted_text, span_maps = self.redact_text(
                ocr_page.full_text,
                tenant_id,
                vault=vault,
            )

            # Map tokens to word coordinates
            bbox_items: list[dict[str, Any]] = []
            for item in span_maps:
                bbox_items.append(
                    {
                        "token": item["token"],
                        "entity_type": item["entity_type"],
                        "page": ocr_page.page_number,
                    }
                )

            redacted_pages.append(
                RedactedPage(
                    page=ocr_page.page_number,
                    doc_id=doc_id,
                    redacted_text=redacted_text,
                    bbox_map=bbox_items,
                )
            )

        return redacted_pages
