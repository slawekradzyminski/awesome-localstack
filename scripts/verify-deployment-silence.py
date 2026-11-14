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
            "            tasks_from: converge",
            "        name: verify",
            "deployment_silence_state: absent",
            "        name: cleanup",
        ],
    )
    require(positions == sorted(positions), "silence must wrap app convergence and verification")
    require(
        "deployment_silence_duration_minutes: 15" in defaults,
        "the automatic safety expiry must remain 15 minutes",
    )
    require(
        "value: PublicEndpointProbeFailed\n" in present,
        "the public endpoint warning alert must be silenced",
    )
    require(
        "value: PrometheusTargetDown\n" in present,
        "the scrape target warning alert must be silenced",
    )
    for critical in ("PublicEndpointProbeFailedCritical", "PrometheusTargetDownCritical"):
        require(critical not in present, f"the critical {critical} alert must never be silenced")
    require("value: public_https" in present, "silence must target the public probe job")
    require("value: public-edge" in present, "silence must target the public edge service")
    require(
        "value: spring_backend_micrometer|spring_consumer_micrometer|spring_warehouse_micrometer"
        "|spring_payment_micrometer|spring_notification_micrometer\n" in present,
        "target silence must cover only the restarted backend, consumer, warehouse-, payment- and "
        "notification-service scrapes",
    )
    require(
        "(deployment_silence_duration_minutes | int) * 60" in present,
        "Alertmanager endsAt must use the bounded duration",
    )
    require(
        "/api/v2/silence/{{ item }}" in absent
        and 'loop: "{{ deployment_silence_ids }}"' in absent,
        "successful verification must expire every exact created silence",
    )

    print("Deployment silence contract verified")


if __name__ == "__main__":
    main()
