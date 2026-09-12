from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "integrations" / "deerflow"
SKILL = MIGRATION / "skills" / "custom" / "orderflow-research" / "SKILL.md"


class DeerFlowMigrationAssetsTests(unittest.TestCase):
    def test_required_assets_exist(self):
        expected = [
            MIGRATION / "README.md",
            MIGRATION / "bootstrap.ps1",
            MIGRATION / "bootstrap.sh",
            SKILL,
            SKILL.parent / "references" / "project-context.md",
            SKILL.parent / "references" / "commands.md",
        ]
        for path in expected:
            self.assertTrue(path.is_file(), path)

    def test_skill_frontmatter_and_specialist_roles(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertRegex(text, r"(?m)^name:\s+orderflow-research\s*$")
        for phrase in (
            "Data integrity",
            "Research validity and statistics",
            "Strategy and backtest validation",
            "Execution safety and risk",
            "Reliability and CI",
            "Observability and deployment",
            "adversarial reviewer and release manager",
        ):
            self.assertIn(phrase, text)

    def test_skill_keeps_research_and_live_boundaries(self):
        text = SKILL.read_text(encoding="utf-8").lower()
        self.assertIn("never claim profitability without genuine untouched out-of-sample evidence", text)
        self.assertIn("automatic live broker/exchange order transmission remains out of scope", text)
        self.assertIn("frozen discovery-v1", text)

    def test_bootstraps_follow_official_install_boundary(self):
        for name in ("bootstrap.ps1", "bootstrap.sh"):
            text = (MIGRATION / name).read_text(encoding="utf-8")
            for required in (
                "git clone https://github.com/bytedance/deer-flow.git",
                "make config",
                "docker info",
                "make docker-init",
                "make check",
                "make install",
                "make docker-start",
                "make dev",
            ):
                self.assertIn(required, text, f"{name}: {required}")
            self.assertNotRegex(text, re.compile(r"(?i)(type|get-content|cat)\s+.*\.env(?:\s|$)"))

    def test_bootstrap_does_not_start_long_running_services(self):
        ps = (MIGRATION / "bootstrap.ps1").read_text(encoding="utf-8")
        sh = (MIGRATION / "bootstrap.sh").read_text(encoding="utf-8")
        self.assertNotRegex(ps, r"(?m)^\s*&\s*make\s+(docker-start|dev)\s*$")
        self.assertNotRegex(sh, r"(?m)^\s*make\s+(docker-start|dev)\s*$")


if __name__ == "__main__":
    unittest.main()
