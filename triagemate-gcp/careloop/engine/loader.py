"""Loads the clinical reference dataset from JSON and validates it.

The four JSON files under careloop/data/ are the Salesforce reference
objects exported and converted by scripts/sf_csv_to_json.py. Swapping the
starter data for the full export is a file copy, nothing more.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import Condition, Mapping, Specialty, Symptom

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Dataset:
    specialties: dict[str, Specialty] = field(default_factory=dict)
    symptoms: dict[str, Symptom] = field(default_factory=dict)
    conditions: dict[str, Condition] = field(default_factory=dict)
    mappings: list[Mapping] = field(default_factory=list)
    mappings_by_symptom: dict[str, list[Mapping]] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {
            "specialties": len(self.specialties),
            "symptoms": len(self.symptoms),
            "conditions": len(self.conditions),
            "mappings": len(self.mappings),
        }

    def validate(self) -> list[str]:
        """Returns a list of integrity problems. Empty list means clean."""
        problems: list[str] = []

        for condition in self.conditions.values():
            if condition.recommended_specialty not in self.specialties:
                problems.append(
                    f"Condition {condition.external_id} points at unknown "
                    f"specialty {condition.recommended_specialty}"
                )

        for mapping in self.mappings:
            if mapping.symptom not in self.symptoms:
                problems.append(
                    f"Mapping {mapping.external_id} points at unknown "
                    f"symptom {mapping.symptom}"
                )
            if mapping.condition not in self.conditions:
                problems.append(
                    f"Mapping {mapping.external_id} points at unknown "
                    f"condition {mapping.condition}"
                )
            if mapping.weight <= 0:
                problems.append(
                    f"Mapping {mapping.external_id} has non-positive weight "
                    f"{mapping.weight}"
                )

        orphans = [
            s.external_id
            for s in self.symptoms.values()
            if not self.mappings_by_symptom.get(s.external_id)
        ]
        if orphans:
            problems.append(
                f"{len(orphans)} symptom(s) map to no condition and can never "
                f"affect a score: {', '.join(sorted(orphans)[:8])}"
                + (" ..." if len(orphans) > 8 else "")
            )

        return problems


def _read(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Reference data missing: {path}. Run "
            f"scripts/sf_csv_to_json.py against your Salesforce export."
        )
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def load_dataset(data_dir: Path | str = DATA_DIR) -> Dataset:
    base = Path(data_dir)
    data = Dataset()

    for row in _read(base / "specialties.json"):
        spec = Specialty(
            external_id=row["external_id"].strip().upper(),
            name=row["name"].strip(),
            description=row.get("description", ""),
        )
        data.specialties[spec.external_id] = spec

    for row in _read(base / "symptoms.json"):
        sym = Symptom(
            external_id=row["external_id"].strip().upper(),
            name=row["name"].strip(),
            body_system=row.get("body_system", "General").strip() or "General",
        )
        data.symptoms[sym.external_id] = sym

    for row in _read(base / "conditions.json"):
        cond = Condition(
            external_id=row["external_id"].strip().upper(),
            name=row["name"].strip(),
            recommended_specialty=row["recommended_specialty"].strip().upper(),
            triage_priority=row["triage_priority"].strip(),
            is_red_flag=_truthy(row.get("is_red_flag", False)),
            clinical_note=row.get("clinical_note", ""),
        )
        data.conditions[cond.external_id] = cond

    index: dict[str, list[Mapping]] = {}
    for row in _read(base / "symptom_condition_map.json"):
        mapping = Mapping(
            external_id=row["external_id"].strip().upper(),
            symptom=row["symptom"].strip().upper(),
            condition=row["condition"].strip().upper(),
            weight=int(row["weight"]),
        )
        data.mappings.append(mapping)
        index.setdefault(mapping.symptom, []).append(mapping)

    data.mappings_by_symptom = index
    return data


_cached: Dataset | None = None


def get_dataset() -> Dataset:
    """Process-wide singleton. Loading is cheap but not free."""
    global _cached
    if _cached is None:
        _cached = load_dataset()
    return _cached
