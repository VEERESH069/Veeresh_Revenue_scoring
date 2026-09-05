"""Generate license, vulnerability, and SBOM evidence without installing packages."""

import json
import subprocess
from importlib import metadata
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def declared_names() -> list[str]:
    names = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", line)
        if match and not line.lstrip().startswith("#"):
            names.append(match.group(1))
    return names


def installed_packages() -> list[dict[str, str]]:
    queue = declared_names()
    seen: set[str] = set()
    rows = []
    while queue:
        name = queue.pop(0)
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            rows.append({"name": name, "version": "NOT_INSTALLED", "license": "UNKNOWN"})
            continue
        name = distribution.metadata.get("Name")
        if name:
            rows.append({"name": name, "version": distribution.version, "license": distribution.metadata.get("License", "UNKNOWN") or "UNKNOWN"})
            for requirement in distribution.requires or []:
                match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
                if match:
                    queue.append(match.group(1))
    rows.sort(key=lambda item: item["name"].lower())
    return rows


def command_status(command: list[str]) -> dict:
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        return {"command": " ".join(command), "available": True, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except FileNotFoundError:
        return {"command": " ".join(command), "available": False, "note": "Tool is not installed in the current runtime."}


def main() -> None:
    packages = installed_packages()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "dependency-license-report.json").write_text(json.dumps({"source": "declared requirements plus installed transitive metadata", "lock_file": None, "packages": packages}, indent=2), encoding="utf-8")
    vulnerability = command_status(["pip-audit", "-r", "requirements.txt", "--format", "json"])
    (REPORTS / "dependency-vulnerability-report.json").write_text(json.dumps(vulnerability, indent=2), encoding="utf-8")
    components = [{"type": "library", "name": row["name"], "version": row["version"], "licenses": [{"license": {"name": row["license"]}}]} for row in packages]
    (REPORTS / "dependency-sbom.json").write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "metadata": {"source": "requirements.txt and installed metadata", "lock_file": None}, "components": components}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()