"""
Modèles de données alignés sur le Google Sheet `tapage_biduleur`.

Une ligne du sheet = un Event (date + lieu + horaire(s) éventuellement multiples)
qui regroupe jusqu'à 4 Acts (artiste/spectacle).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Genre(str, Enum):
    """Col K du sheet."""
    SPECTACLE_VIVANT = "sv"
    CONCERT = "c"
    EXPO = "expo"
    DJ = "dj"
    AUTRE = "autre"


class Act(BaseModel):
    """Un artiste / spectacle / compagnie ; jusqu'à 4 par Event (cols K-N, O-R, S-V, W-Z)."""
    genre: Genre
    title: str | None = None              # nom du spectacle (col L pour SV)
    performer: str                         # artiste/compagnie (col M pour concerts/SV)
    style: str | None = None               # ex. "Acrobatie / Portés", "Jazz / Pop"


class Event(BaseModel):
    """Une ligne du Google Sheet."""

    # Métadonnées (cols A-B)
    tapeur_email: str = Field(..., description="Col A — INFO TAPEUR")
    tapage_iso: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z",
                             description="Col B — DATE TAPAGE (ISO UTC)")

    # Festoche (cols D-E)
    festival: str | None = None            # Col D — FESTOCHE
    festival_style: str | None = None      # Col E — STYLE FESTOCHE

    # Localisation temporelle et spatiale (cols F-I)
    date_label: str = Field(..., description="Col F — ex. 'Vendredi 22'")
    date_iso: str = Field(..., description="Format YYYY-MM-DD pour filtrage interne")
    times: list[str] = Field(..., description="Col G — ex. ['18h30', '20h30'] ; joints par ' & '")
    venue: str = Field(..., description="Col H — LIEU (canonicalisé via mappings.yaml)")
    city: str = Field(..., description="Col I — VILLE")

    # Tarif (col J)
    price: str = Field(..., description="Col J — ex. 'gratuit', '7€', '12 à 15€', '?'")

    # Mode festival : si True, l'export CSV met "Festivals" dans la col DATE
    # (marqueur magique reconnu par biduleur — section dédiée style onliner,
    # cf. lebidul/biduleur#106). Le festival/festival_style portent le nom et
    # la description ; venue/times sont rendus vides au CSV même si renseignés
    # dans le schema. À utiliser via `mode: festival_onliner` côté config source.
    is_festival: bool = False

    # Programmation : 1 à 4 acts (cols K-N, O-R, S-V, W-Z)
    acts: list[Act] = Field(..., min_length=1, max_length=4)

    # Source tracking (pas dans le sheet, utile pour debug/dédup).
    # Pas exclu de model_dump() : on en a besoin pour rejouer le cache disque
    # entre `normalize` et `preview`. Le CSV ne les inclut pas, car
    # validate.event_to_row() construit la ligne champ par champ.
    source_kind: Literal["outlook", "web", "pdf", "fb", "image"]
    source_ref: str = Field(..., description="URL / message-id / chemin fichier")

    @field_validator("times")
    @classmethod
    def at_least_one_time(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("times must contain at least one entry")
        return v

    def time_str(self) -> str:
        """Représentation des horaires telle qu'écrite dans le sheet."""
        return " & ".join(self.times)

    def fingerprint(self) -> str:
        """Pour dédoublonnage.

        Mode classique : (date, premier horaire, lieu, premier artiste).
        Mode festival : (nom du festival, ville) — venue/times non pertinents
        car rendus vides au CSV, mais le festival a un nom unique par ville.
        """
        if self.is_festival:
            fest = (self.festival or "").lower().strip()
            return f"festival:{fest}|{self.city.lower().strip()}"
        first_act = self.acts[0].performer.lower().strip()
        first_time = self.times[0].lower().strip()
        return f"{self.date_iso}|{first_time}|{self.venue.lower().strip()}|{first_act}"


class CollectedItem(BaseModel):
    """JSON brut produit par un connecteur, avant normalisation Claude."""
    source_kind: Literal["outlook", "web", "pdf", "fb", "image"]
    source_ref: str                        # URL / message-id / path
    fetched_at: str                        # ISO timestamp
    raw_text: str | None = None            # texte / HTML / markdown
    raw_image_b64: str | None = None       # pour images (base64 PNG/JPEG)
    raw_metadata: dict = Field(default_factory=dict)  # ex. headers email, sender FB, etc.
