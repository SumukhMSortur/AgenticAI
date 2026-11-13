"""Generates synthetic multi-year factory audit histories and failure labels."""

import json
import math
from pathlib import Path

import numpy as np

DATA_DIR = Path("data/synthetic")
TRAIN_FILE = DATA_DIR / "audit_histories_train.json"
VAL_FILE = DATA_DIR / "audit_histories_val.json"
TEST_FILE = DATA_DIR / "audit_histories_test.json"

COUNTRIES = [
    "Bangladesh",
    "Vietnam",
    "India",
    "Turkey",
    "Portugal",
    "Cambodia",
    "Indonesia",
    "Pakistan",
]


def generate_factory_history(
    factory_idx: int,
    rng: np.random.Generator,
    num_months: int = 36,
) -> dict:
    """Generates 36-month time series for one factory using a latent hazard process."""
    factory_id = f"FACT-{factory_idx:04d}"
    country = COUNTRIES[factory_idx % len(COUNTRIES)]
    name = f"{country} Apparel Mill #{factory_idx:03d}"

    # Latent factory quality parameter (higher means safer)
    latent_quality = float(rng.beta(2.5, 2.5))  # 0..1 centered around 0.5

    # Determine whether the factory experiences a systemic drift towards failure in month 31-36
    will_fail = bool(rng.random() > (0.2 + 0.65 * latent_quality))

    # Time series arrays
    months_series = []
    drift_onset = rng.integers(24, 30) if will_fail else 999

    for m in range(num_months):
        # Seasonality: higher pressure in Q3/Q4 peak production months
        seasonal_factor = 1.0 + 0.15 * math.sin(2 * math.pi * (m % 12) / 12.0)

        # Failure drift
        drift = max(0.0, (m - drift_onset) * 0.18) if will_fail else 0.0

        # Signals
        # 1. Carbon intensity (kg CO2e per kg fabric: baseline ~12-25)
        carbon_base = 25.0 - (latent_quality * 10.0) + drift * 2.0
        carbon = float(np.clip(rng.normal(carbon_base * seasonal_factor, 1.5), 8.0, 45.0))

        # 2. Labor violation count (per quarter/month)
        labor_lam = max(0.05, (1.0 - latent_quality) * 1.5 + drift * 1.2)
        labor_violations = int(rng.poisson(labor_lam))

        # 3. Certificate lapse days
        if rng.random() < (0.05 + 0.25 * (1.0 - latent_quality) + 0.1 * drift):
            cert_lapse_days = int(rng.integers(5, 60 + int(drift * 10)))
        else:
            cert_lapse_days = 0

        # 4. Corrective action backlog count
        backlog_base = max(0, int((1.0 - latent_quality) * 8 + drift * 5 + rng.normal(0, 1.5)))
        backlog = int(np.clip(backlog_base, 0, 30))

        # 5. Worker safety incident count
        safety_lam = max(0.02, (1.0 - latent_quality) * 0.8 + drift * 0.9)
        safety_incidents = int(rng.poisson(safety_lam))

        months_series.append(
            {
                "month": m + 1,
                "carbon_intensity": round(carbon, 2),
                "labor_violations": labor_violations,
                "cert_lapse_days": cert_lapse_days,
                "corrective_action_backlog": backlog,
                "safety_incidents": safety_incidents,
            }
        )

    # Calibrated probability of failure in next 6 months
    final_3m_violations = sum(item["labor_violations"] for item in months_series[-3:])
    final_3m_backlog = months_series[-1]["corrective_action_backlog"]
    risk_score = 1.0 / (
        1.0
        + math.exp(
            -(
                2.5 * (1.0 - latent_quality)
                + 0.3 * final_3m_violations
                + 0.15 * final_3m_backlog
                - 2.8
            )
        )
    )
    risk_score = float(np.clip(risk_score, 0.01, 0.99))

    return {
        "factory_id": factory_id,
        "name": name,
        "country": country,
        "latent_quality": round(latent_quality, 4),
        "will_fail_next_6m": will_fail,
        "p_fail_6m": round(risk_score, 4),
        "history": months_series,
    }


def generate_audit_histories(
    num_factories: int = 450,
    seed: int = 42,
) -> tuple[Path, Path, Path]:
    """Generates stratified train/val/test splits of audit histories."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    factories = [generate_factory_history(i + 1, rng) for i in range(num_factories)]

    # Stratified split by factory failure label (70% train, 15% val, 15% test)
    failing = [f for f in factories if f["will_fail_next_6m"]]
    passing = [f for f in factories if not f["will_fail_next_6m"]]

    rng.shuffle(failing)
    rng.shuffle(passing)

    def split_group(group: list) -> tuple[list, list, list]:
        n = len(group)
        n_train = int(0.70 * n)
        n_val = int(0.15 * n)
        return group[:n_train], group[n_train : n_train + n_val], group[n_train + n_val :]

    train_f, val_f, test_f = split_group(failing)
    train_p, val_p, test_p = split_group(passing)

    train_set = train_f + train_p
    val_set = val_f + val_p
    test_set = test_f + test_p

    rng.shuffle(train_set)
    rng.shuffle(val_set)
    rng.shuffle(test_set)

    for path, data in [(TRAIN_FILE, train_set), (VAL_FILE, val_set), (TEST_FILE, test_set)]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generator_version": "1.0.0",
                    "seed": seed,
                    "is_synthetic": True,
                    "notes": "Synthetic audit histories generated via latent hazard process with drift and seasonality.",
                    "factory_count": len(data),
                    "factories": data,
                },
                f,
                indent=2,
            )

    print(
        f"Generated audit histories (Seed: {seed}): "
        f"Train={len(train_set)}, Val={len(val_set)}, Test={len(test_set)} "
        f"(Total={num_factories}, Positive rate={len(failing) / num_factories:.2%})"
    )
    return TRAIN_FILE, VAL_FILE, TEST_FILE


if __name__ == "__main__":
    generate_audit_histories()
