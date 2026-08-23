"""Content bundle loading and validation.

A bundle is a YAML file of items/deposits/recipes/buildings plus tuning
numbers. Named bundles ("slice") resolve to files under reco/content/.
The loaded dict carries a content_hash over its canonical form — recorded in
run manifests so a log is permanently pinned to the exact dataset that produced it.
"""
import os

import yaml

from reco.engine.hashing import sha256_hex

_CONTENT_DIR = os.path.join(os.path.dirname(__file__), "..", "content")


class ContentError(Exception):
    """Content bundle is malformed or has broken cross-references."""


def load_content(name_or_path) -> dict:
    path = str(name_or_path)
    if not path.endswith(".yaml"):
        path = os.path.join(_CONTENT_DIR, f"{path}.yaml")
    with open(path, encoding="utf-8") as f:
        content = yaml.safe_load(f)
    _validate(content)
    content["content_hash"] = sha256_hex(content)
    return content


def _validate(content: dict) -> None:
    items = content["items"]
    buildings = content["buildings"]

    professions = content.get("professions", {})
    for name, recipe in content["recipes"].items():
        for item in recipe["inputs"]:
            if item not in items:
                raise ContentError(f"recipe {name}: unknown input item {item!r}")
        if name not in items:
            raise ContentError(f"recipe {name}: output is not a known item")
        station = recipe["station"]
        if station is not None and station not in buildings:
            raise ContentError(f"recipe {name}: unknown station {station!r}")
        profession = recipe.get("profession")
        if profession is not None and profession not in professions:
            raise ContentError(f"recipe {name}: unknown profession {profession!r}")
        if recipe["ticks"] > 1 and station is None:
            raise ContentError(f"recipe {name}: multi-tick recipes need a station")

    for name, deposit in content["deposits"].items():
        if deposit["yields"] not in items:
            raise ContentError(f"deposit {name}: unknown yield item {deposit['yields']!r}")
        profession = deposit.get("profession")
        if profession is not None and profession not in professions:
            raise ContentError(f"deposit {name}: unknown profession {profession!r}")

    for name, building in buildings.items():
        for item in building["materials"]:
            if item not in items:
                raise ContentError(f"building {name}: unknown material {item!r}")

    for item in content["project"]["needs"]:
        if item not in items:
            raise ContentError(f"project: unknown needed item {item!r}")
