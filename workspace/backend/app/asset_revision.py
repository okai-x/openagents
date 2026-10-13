"""Stable revisions for conditional Git asset publishing."""
import hashlib
import json


def asset_revision(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
