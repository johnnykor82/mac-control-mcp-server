#!/usr/bin/env python3
"""Read-only E9 review of pinned Python distributions' declared license metadata.

This is an inventory, not a legal determination, source provenance guarantee,
license text bundling check or a package vulnerability scan.
"""
from __future__ import annotations

from importlib import metadata
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"[-_.]+")
PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s]+)$")


def canonical(name: str) -> str:
    return NAME_RE.sub("-", name).lower()


def declared_license(dist) -> str:
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    for classifier in meta.get_all("Classifier", []):
        if classifier.startswith("License :: "):
            return classifier[len("License :: "):].strip()
    plain = (meta.get("License") or "").strip()
    if plain and len(plain) <= 120 and "\n" not in plain:
        return plain
    return ""


def audit_requirements(requirements: Path) -> dict:
    pins = {}
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN_RE.fullmatch(line)
        if not match:
            raise ValueError("Unpinned or unsupported requirement")
        name, version = match.groups()
        key = canonical(name)
        if key in pins:
            raise ValueError("Duplicate normalized requirement: " + key)
        pins[key] = version

    installed = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            installed[canonical(name)] = dist
    packages = []
    for key, version in sorted(pins.items()):
        dist = installed.get(key)
        license_name = declared_license(dist) if dist else ""
        found = dist.version if dist else None
        packages.append({
            "name": key, "pinned": version, "installed": found,
            "license_declaration": license_name or None,
        })
    return {
        "schema": 1, "pinned_count": len(pins),
        "unresolved": [v["name"] for v in packages if not v["license_declaration"]],
        "mismatched_versions": [v["name"] for v in packages if v["installed"] != v["pinned"]],
        "packages": packages,
        "limitations": [
            "Metadata license classifications are self-reported, not legal verification.",
            "Bundled notices, transitive non-Python packages, source provenance and trademark rights need separate review.",
        ],
    }


if __name__ == "__main__":
    report = audit_requirements(ROOT / "requirements/dev-frozen.txt")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(1 if report["unresolved"] or report["mismatched_versions"] else 0)
