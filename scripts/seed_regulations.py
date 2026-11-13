#!/usr/bin/env python3
"""Seed the ChromaDB vector store with regulations from data/regulations/csddd_regulations.json."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.rag.chunker import chunk_regulations
from backend.app.rag.store import ChromaVectorStore

REGULATIONS_FILE = Path("data/regulations/csddd_regulations.json")
CHROMA_DIR = ".chroma"


def main() -> None:
    if not REGULATIONS_FILE.exists():
        print(f"Error: {REGULATIONS_FILE} not found. Run make data first.")
        sys.exit(1)

    print(f"Chunking regulations from {REGULATIONS_FILE}...")
    chunks = chunk_regulations(REGULATIONS_FILE)
    print(f"  -> {len(chunks)} chunks generated.")

    print(f"Connecting to ChromaDB at {CHROMA_DIR}...")
    store = ChromaVectorStore(persist_dir=CHROMA_DIR)

    print("Upserting chunks...")
    store.upsert_chunks(chunks)
    print(f"Done. Store now contains {store.count()} chunks.")


if __name__ == "__main__":
    main()
