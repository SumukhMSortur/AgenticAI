"""OCR extraction with word-level bounding boxes normalized to 0-1000 space."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pymupdf
from pydantic import BaseModel

from backend.app.domain.models import BBox


class OcrWord(BaseModel):
    """Single OCR word with spatial bounding box in 0-1000 coordinate space."""

    text: str
    bbox: BBox
    page: int
    confidence: float = 1.0


class OcrPageResult(BaseModel):
    """OCR extraction result for a single page."""

    page_number: int
    full_text: str
    words: list[OcrWord]


class IOcrEngine(ABC):
    """Abstract interface for local OCR processing."""

    @abstractmethod
    def extract_document(self, file_path: Path) -> list[OcrPageResult]:
        """Extracts text and word bounding boxes for all pages of a document."""
        pass


class PyMuPdfOcrEngine(IOcrEngine):
    """Local PDF text extraction using PyMuPDF vector & text word coordinates."""

    def extract_document(self, file_path: Path) -> list[OcrPageResult]:
        doc: Any = pymupdf.open(str(file_path))
        results: list[OcrPageResult] = []

        try:
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                width = page.rect.width or 595.0
                height = page.rect.height or 842.0

                # page.get_text("words") returns tuples: (x0, y0, x1, y1, word, block_no, line_no, word_no)
                raw_words = page.get_text("words")
                words: list[OcrWord] = []

                for w in raw_words:
                    x0, y0, x1, y1, word_text = (
                        float(w[0]),
                        float(w[1]),
                        float(w[2]),
                        float(w[3]),
                        str(w[4]),
                    )
                    # Normalize to 0-1000
                    norm_x0 = max(0, min(1000, int(round((x0 / width) * 1000))))
                    norm_y0 = max(0, min(1000, int(round((y0 / height) * 1000))))
                    norm_x1 = max(norm_x0, min(1000, int(round((x1 / width) * 1000))))
                    norm_y1 = max(norm_y0, min(1000, int(round((y1 / height) * 1000))))

                    box = BBox(x0=norm_x0, y0=norm_y0, x1=norm_x1, y1=norm_y1)
                    words.append(
                        OcrWord(
                            text=word_text,
                            bbox=box,
                            page=page_idx + 1,
                            confidence=0.99,
                        )
                    )

                page_text = page.get_text()
                results.append(
                    OcrPageResult(
                        page_number=page_idx + 1,
                        full_text=page_text,
                        words=words,
                    )
                )
        finally:
            doc.close()

        return results


def get_ocr_engine() -> IOcrEngine:
    """Returns the configured OCR engine (PyMuPDF by default)."""
    return PyMuPdfOcrEngine()
