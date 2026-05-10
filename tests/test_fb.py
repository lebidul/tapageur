"""Tests du connecteur Facebook (parsing pur, sans appel API)."""
from __future__ import annotations

from tapageur.connectors.fb import _is_blocked, _post_to_item


def test_post_with_message_only():
    """Post simple avec juste un message texte."""
    post = {
        "id": "123_456",
        "created_time": "2026-05-07T17:30:06+0000",
        "message": "Concert vendredi 22 mai à 20h30 au Chapiteau.",
        "permalink_url": "https://facebook.com/123/posts/456",
    }
    item = _post_to_item(post)
    assert item is not None
    assert item.source_kind == "fb"
    assert item.source_ref == "fb:123_456"
    assert "Concert vendredi 22 mai" in item.raw_text
    assert item.raw_metadata["post_id"] == "123_456"
    assert item.raw_metadata["page"] == "Le Bidul"


def test_post_with_story_and_message():
    """Story (action auto) + message du user → les deux dans raw_text."""
    post = {
        "id": "123_789",
        "created_time": "2026-05-07T13:27:45+0000",
        "story": "Le Bidul a partagé un événement.",
        "message": "À ne pas rater !",
    }
    item = _post_to_item(post)
    assert item is not None
    assert "[story] Le Bidul a partagé un événement." in item.raw_text
    assert "À ne pas rater" in item.raw_text


def test_post_with_blocked_attachment_drops_attachment_only():
    """Attachment 'Ce contenu n'est pas disponible' → filtré, mais on garde
    quand même l'URL target s'il y en a une (peut être un event URL utile)."""
    post = {
        "id": "1_1",
        "message": "Voir l'event partagé.",
        "attachments": {
            "data": [{
                "type": "native_templates",
                "title": "Ce contenu n'est pas disponible actuellement",
                "description": "Privacy stuff blabla",
                "target": {"url": "https://facebook.com/events/12345"},
            }]
        }
    }
    item = _post_to_item(post)
    assert item is not None
    # Le titre/desc bloqué est filtré
    assert "Ce contenu n'est pas" not in item.raw_text
    assert "Privacy stuff" not in item.raw_text
    # Mais le message et l'URL target sont conservés
    assert "Voir l'event partagé" in item.raw_text
    assert "facebook.com/events/12345" in item.raw_text


def test_post_with_photo_attachment_keeps_description():
    """Attachment photo avec description utile → on garde tout."""
    post = {
        "id": "1_2",
        "message": "",
        "attachments": {
            "data": [{
                "type": "photo",
                "title": "",
                "description": "Concert au Chapiteau vendredi 22 mai à 20h30, entrée 10€.",
                "url": "https://facebook.com/photo/abc",
            }]
        }
    }
    item = _post_to_item(post)
    assert item is not None
    assert "Concert au Chapiteau" in item.raw_text


def test_post_empty_returns_none():
    """Post sans message, sans story, attachment vide → None (skip)."""
    post = {"id": "1_3"}
    assert _post_to_item(post) is None


def test_post_only_blocked_attachment_returns_none_if_no_message():
    """Post sans message et avec UNIQUEMENT un attachment bloqué sans target_url
    → rien d'utile, skip."""
    post = {
        "id": "1_4",
        "attachments": {
            "data": [{
                "type": "native_templates",
                "title": "Ce contenu n'est pas disponible actuellement",
                "description": "...",
            }]
        }
    }
    assert _post_to_item(post) is None


def test_post_only_blocked_attachment_with_url_kept():
    """Post sans message, attachment bloqué MAIS avec target_url → on garde
    car l'URL peut être un event utile."""
    post = {
        "id": "1_5",
        "attachments": {
            "data": [{
                "type": "native_templates",
                "title": "Ce contenu n'est pas disponible actuellement",
                "target": {"url": "https://facebook.com/events/777"},
            }]
        }
    }
    item = _post_to_item(post)
    assert item is not None
    assert "facebook.com/events/777" in item.raw_text


def test_post_multiple_attachments():
    """Plusieurs attachments → tous concaténés dans raw_text."""
    post = {
        "id": "1_6",
        "message": "Notre actu :",
        "attachments": {
            "data": [
                {"type": "photo", "description": "Affiche 1"},
                {"type": "photo", "description": "Affiche 2"},
            ]
        }
    }
    item = _post_to_item(post)
    assert item is not None
    assert "Affiche 1" in item.raw_text
    assert "Affiche 2" in item.raw_text


def test_post_no_id_returns_none():
    """Post sans id → invalide, skip."""
    assert _post_to_item({"message": "x"}) is None


def test_is_blocked():
    assert _is_blocked("Ce contenu n'est pas disponible actuellement") is True
    assert _is_blocked("This content isn't available") is True
    assert _is_blocked("Concert au Chapiteau") is False
    assert _is_blocked("") is False


def test_noise_story_filtered_when_alone():
    """Story système 'a actualisé son statut' SANS autre contenu → skip."""
    post = {
        "id": "1_noise",
        "story": "Le Bidul a actualisé son statut.",
    }
    assert _post_to_item(post) is None


def test_noise_story_kept_when_message_present():
    """Story système mais avec un vrai message → on garde le post."""
    post = {
        "id": "1_keep",
        "story": "Le Bidul a actualisé son statut.",
        "message": "Concert vendredi 22 mai 20h30 au Chapiteau.",
    }
    item = _post_to_item(post)
    assert item is not None
    assert "Concert vendredi" in item.raw_text


def test_noise_story_kept_when_useful_attachment():
    """Story système + attachment non-bloqué avec contenu → on garde."""
    post = {
        "id": "1_keep2",
        "story": "Le Bidul a changé sa photo de profil.",
        "attachments": {
            "data": [{
                "type": "photo",
                "description": "Affiche du festival 25 mai",
            }]
        }
    }
    item = _post_to_item(post)
    assert item is not None
    assert "Affiche du festival" in item.raw_text


def test_useful_story_kept():
    """Story 'a créé un évènement' ou 'participe à un évènement' → toujours utile."""
    post = {
        "id": "1_event",
        "story": "Le Bidul a créé un évènement.",
        "attachments": {
            "data": [{
                "type": "event",
                "title": "Bidul En Fête #11",
                "target": {"url": "https://facebook.com/events/123"},
            }]
        }
    }
    item = _post_to_item(post)
    assert item is not None
    assert "Bidul En Fête" in item.raw_text
