#!/usr/bin/env python3
"""Verify the production deployment-alert silence contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible/playbooks/deploy.yml"
DEFAULTS = ROOT / "ansible/roles/deployment_silence/defaults/main.yml"
PRESENT = ROOT / "ansible/roles/deployment_silence/tasks/present.yml"
ABSENT = ROOT / "ansible/roles/deployment_silence/tasks/absent.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"Deployment silence contract failed: {message}")


def ordered_positions(text: str, markers: list[str]) -> list[int]:
    positions = [text.find(marker) for marker in markers]
    require(all(position >= 0 for position in positions), "deploy role sequence is incomplete")
    return positions


def main() -> None:
    playbook = PLAYBOOK.read_text()
    defaults = DEFAULTS.read_text()
    present = PRESENT.read_text()
    absent = ABSENT.read_text()

    positions = ordered_positions(
        playbook,
        [
            "deployment_silence_state: present",
            "    - app",
            "    - verify",
            "deployment_silence_state: absent",
            "    - cleanup",
        ],
    )
    require(positions == sorted(positions), "silence must wrap app convergence and verification")
    require(
        "deployment_silence_duration_minutes: 15" in defaults,
        "the automatic safety expiry must remain 15 minutes",
    )
    require(
        "'value': 'PublicEndpointProbeFailed'" in present,
        "the warning alert must be silenced",
    )
    require(
        "'value': 'PublicEndpointProbeFailedCritical'" not in present,
        "the critical alert must never be silenced",
    )
    require("'value': 'public_https'" in present, "silence must target the public probe job")
    require("'value': 'public-edge'" in present, "silence must target the public edge service")
    require(
        "(deployment_silence_duration_minutes | int) * 60" in present,
        "Alertmanager endsAt must use the bounded duration",
    )
    require(
        "/api/v2/silence/{{ deployment_silence_id }}" in absent,
        "successful verification must expire the exact created silence",
    )

    print("Deployment silence contract verified")


if __name__ == "__main__":
    main()
