"""Generates structured regulation corpus with date and version metadata."""

import json
from pathlib import Path

REGULATIONS_DIR = Path("data/regulations")
REGULATIONS_FILE = REGULATIONS_DIR / "csddd_regulations.json"

REGULATIONS_CORPUS = [
    # 1. Superseded Directive (EU) 2024/1760 (Initial CSDDD text before Omnibus I)
    {
        "regulation_id": "EU-CSDDD-2024",
        "version_id": "EU-CSDDD-2024-1760",
        "title": "Directive (EU) 2024/1760 on corporate sustainability due diligence (Original text)",
        "jurisdiction": "EU",
        "effective_from": "2024-07-25",
        "superseded_by": "EU-CSDDD-2026-470",
        "status": "superseded",
        "sections": [
            {
                "section_id": "SEC-2024-ART-01",
                "kind": "article",
                "article": "Article 1",
                "title": "Subject matter and scope",
                "text": "This Directive lays down rules on obligations for in-scope companies regarding adverse human rights impacts and adverse environmental impacts, arising from their own operations, those of their subsidiaries, and those of their business partners in the chains of activities.",
                "keywords": [
                    "due diligence",
                    "adverse impacts",
                    "human rights",
                    "chain of activities",
                ],
            },
            {
                "section_id": "SEC-2024-ART-02",
                "kind": "article",
                "article": "Article 2",
                "title": "Scope of application (Original thresholds)",
                "text": "This Directive applies to European Union companies having more than 1,000 employees on average and a net worldwide turnover of more than EUR 450,000,000 in the last financial year.",
                "keywords": ["thresholds", "1000 employees", "450 million turnover", "scope"],
            },
            {
                "section_id": "SEC-2024-ART-15",
                "kind": "article",
                "article": "Article 15",
                "title": "Combating climate change (Transition plan)",
                "text": "Companies shall adopt and put into effect a transition plan for climate change mitigation which aims to ensure, through best efforts, that the business model and strategy of the company are compatible with the transition to a sustainable economy and the 1.5 °C limit.",
                "keywords": ["climate transition plan", "1.5 degrees", "Paris agreement"],
            },
            {
                "section_id": "SEC-2024-ART-22",
                "kind": "article",
                "article": "Article 22",
                "title": "Civil liability of companies",
                "text": "Member States shall ensure that a company is held liable for a damage caused to a natural or legal person where the company intentionally or negligently failed to comply with the obligations laid down in Articles 7 and 8.",
                "keywords": ["civil liability", "damages", "private enforcement"],
            },
        ],
    },
    # 2. Amended Directive (EU) 2026/470 (Omnibus I Directive in force since 18 March 2026)
    {
        "regulation_id": "EU-CSDDD-2026",
        "version_id": "EU-CSDDD-2026-470",
        "title": "Directive (EU) 2026/470 amending Directive 2024/1760 (Omnibus I reform)",
        "jurisdiction": "EU",
        "effective_from": "2026-03-18",
        "superseded_by": None,
        "status": "in_force",
        "sections": [
            {
                "section_id": "SEC-2026-ART-01",
                "kind": "article",
                "article": "Article 1",
                "title": "Scope and revised application thresholds under Omnibus I",
                "text": "Directive (EU) 2024/1760 is amended as follows: It applies strictly to companies which had more than 5,000 employees on average and generated a net worldwide turnover of more than EUR 1,500,000,000 in the last financial year. A single application date is established for 26 July 2029.",
                "keywords": ["Omnibus I", "5000 employees", "1.5 billion turnover", "26 July 2029"],
            },
            {
                "section_id": "SEC-2026-ART-05",
                "kind": "article",
                "article": "Article 5",
                "title": "Risk-based supplier due diligence and verification",
                "text": "In-scope companies shall conduct risk-based human rights and environmental due diligence across tier-1 and identified high-risk upstream suppliers. Companies must verify certificates, audit reports, and bills of materials against accredited independent issuer registries.",
                "keywords": ["risk-based", "verification", "tier-1", "accredited registry", "BOM"],
            },
            {
                "section_id": "SEC-2026-ART-08",
                "kind": "article",
                "article": "Article 8",
                "title": "Prevention of potential adverse impacts",
                "text": "Companies shall take appropriate measures to prevent or adequately mitigate potential adverse impacts, including seeking contractual assurances from direct business partners and verifying compliance with contractual terms through independent third-party audits.",
                "keywords": [
                    "prevention",
                    "mitigation",
                    "contractual assurances",
                    "third-party audits",
                ],
            },
            {
                "section_id": "SEC-2026-ART-11",
                "kind": "article",
                "article": "Article 11",
                "title": "Removal of separate climate transition plan and civil liability regime",
                "text": "Articles 15 and 22 of Directive (EU) 2024/1760 are deleted. Value chain mapping is conducted solely as a risk-based exercise without standalone civil liability regime under this Directive.",
                "keywords": ["deletion", "transition plan removed", "civil liability removed"],
            },
        ],
    },
    # 3. EU ESPR Regulation (EU) 2024/1781 (Digital Product Passport & Textiles)
    {
        "regulation_id": "EU-ESPR-2024",
        "version_id": "EU-ESPR-2024-1781",
        "title": "Regulation (EU) 2024/1781 Ecodesign for Sustainable Products Regulation (ESPR)",
        "jurisdiction": "EU",
        "effective_from": "2024-07-18",
        "superseded_by": None,
        "status": "in_force",
        "sections": [
            {
                "section_id": "SEC-ESPR-ART-08",
                "kind": "article",
                "article": "Article 8",
                "title": "Digital Product Passport requirements for textiles",
                "text": "Textile products placed on the European market must possess a Digital Product Passport (DPP) containing verified composition data, certified organic or recycled fiber percentages, chemical compliance (substances of very high concern below threshold), and facility origin identification.",
                "keywords": [
                    "Digital Product Passport",
                    "DPP",
                    "textiles",
                    "organic fiber",
                    "chemical compliance",
                ],
            },
            {
                "section_id": "SEC-ESPR-ART-10",
                "kind": "article",
                "article": "Article 10",
                "title": "Traceability and chain of custody evidence",
                "text": "Economic operators shall ensure that all claims regarding recycled content or organic origin are substantiated by transaction certificates, bills of materials, and chain of custody documentation issued by accredited conformity assessment bodies.",
                "keywords": [
                    "traceability",
                    "chain of custody",
                    "transaction certificate",
                    "conformity assessment",
                ],
            },
        ],
    },
]


def generate_regulations() -> Path:
    """Generates the versioned regulation corpus JSON file."""
    REGULATIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REGULATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(REGULATIONS_CORPUS, f, indent=2)

    total_sections = sum(len(r["sections"]) for r in REGULATIONS_CORPUS)
    print(
        f"Generated {len(REGULATIONS_CORPUS)} regulations with {total_sections} sections at {REGULATIONS_FILE}"
    )
    return REGULATIONS_FILE


if __name__ == "__main__":
    generate_regulations()
