"""Carica il catalogo esercizi dai CSV versionati in `data/catalog/`.

    python manage.py load_catalog

È il canale d'import "da amministratore" del progetto, distinto dall'import CSV
dello storico allenamenti, che passa invece da un form web. Il comando è
**idempotente**: rieseguirlo aggiorna le righe esistenti invece di duplicarle,
così correggere un nome nel CSV e ricaricare è un'operazione sicura.
"""

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from training.models import Equipment, Exercise, Muscle, MuscleGroup

FILES = ("muscle_groups.csv", "muscles.csv", "equipment.csv", "exercises.csv")


class Command(BaseCommand):
    help = "Carica gruppi muscolari, muscoli, attrezzi ed esercizi dai CSV in data/catalog/."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=Path,
            default=Path(settings.BASE_DIR) / "data" / "catalog",
            help="Cartella che contiene i quattro CSV del catalogo.",
        )

    def handle(self, *args, **options):
        path: Path = options["path"]
        for name in FILES:
            if not (path / name).exists():
                raise CommandError(f"Manca {path / name}")

        # Un solo blocco atomico: un catalogo caricato a metà è peggio di nessun
        # catalogo, perché le analisi girerebbero su muscoli scoperti senza dirlo.
        with transaction.atomic():
            groups = self._load_groups(path / "muscle_groups.csv")
            muscles = self._load_muscles(path / "muscles.csv")
            equipment = self._load_equipment(path / "equipment.csv")
            exercises = self._load_exercises(path / "exercises.csv", muscles, equipment)

        self.stdout.write(
            self.style.SUCCESS(
                f"Catalogo caricato: {groups} gruppi, {len(muscles)} muscoli, "
                f"{len(equipment)} attrezzi, {exercises} esercizi."
            )
        )

    def _rows(self, csv_path):
        with csv_path.open(encoding="utf-8", newline="") as handle:
            for lineno, row in enumerate(csv.DictReader(handle), start=2):
                yield lineno, {k: (v or "").strip() for k, v in row.items()}

    def _int(self, value, field, csv_path, lineno):
        try:
            return int(value)
        except ValueError:
            raise CommandError(f"{csv_path.name}:{lineno}: {field} non è un intero: {value!r}")

    def _load_groups(self, csv_path):
        count = 0
        for lineno, row in self._rows(csv_path):
            MuscleGroup.objects.update_or_create(
                code=row["code"],
                defaults={
                    "label_it": row["label_it"],
                    "sort_order": self._int(row["sort_order"], "sort_order", csv_path, lineno),
                },
            )
            count += 1
        return count

    def _load_muscles(self, csv_path):
        groups = {g.code: g for g in MuscleGroup.objects.all()}
        muscles = {}
        for lineno, row in self._rows(csv_path):
            group = groups.get(row["group_code"])
            if group is None:
                raise CommandError(
                    f"{csv_path.name}:{lineno}: gruppo sconosciuto {row['group_code']!r}"
                )
            muscle, _ = Muscle.objects.update_or_create(
                code=row["code"],
                defaults={
                    "group": group,
                    "label_it": row["label_it"],
                    "sort_order": self._int(row["sort_order"], "sort_order", csv_path, lineno),
                },
            )
            muscles[muscle.code] = muscle
        return muscles

    def _load_equipment(self, csv_path):
        equipment = {}
        for lineno, row in self._rows(csv_path):
            try:
                bar_weight = Decimal(row["default_bar_weight_kg"])
            except InvalidOperation:
                raise CommandError(
                    f"{csv_path.name}:{lineno}: default_bar_weight_kg non è un numero: "
                    f"{row['default_bar_weight_kg']!r}"
                )
            item, _ = Equipment.objects.update_or_create(
                code=row["code"],
                defaults={
                    "label_it": row["label_it"],
                    "default_bar_weight_kg": bar_weight,
                    "sort_order": self._int(row["sort_order"], "sort_order", csv_path, lineno),
                },
            )
            equipment[item.code] = item
        return equipment

    def _load_exercises(self, csv_path, muscles, equipment):
        count = 0
        for lineno, row in self._rows(csv_path):
            muscle = muscles.get(row["muscle_code"])
            if muscle is None:
                raise CommandError(
                    f"{csv_path.name}:{lineno}: muscolo sconosciuto {row['muscle_code']!r}"
                )
            item = equipment.get(row["equipment_code"])
            if item is None:
                raise CommandError(
                    f"{csv_path.name}:{lineno}: attrezzo sconosciuto {row['equipment_code']!r}"
                )
            Exercise.objects.update_or_create(
                name=row["name"],
                defaults={"primary_muscle": muscle, "equipment": item},
            )
            count += 1
        return count
