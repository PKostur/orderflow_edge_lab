from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RufloIntegrationTests(unittest.TestCase):
    def test_project_agent_contract_preserves_research_and_live_boundaries(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8").lower()
        self.assertIn("ruflo meta-harness", text)
        self.assertIn("deerflow", text)
        self.assertIn("untouched out-of-sample", text)
        self.assertIn("automatic live broker or exchange order transmission remains disabled", text)
        self.assertIn("never store api keys", text)

    def test_ruflo_skill_keeps_repository_as_executable_source_of_truth(self):
        text = (ROOT / ".agents" / "skills" / "orderflow-research" / "SKILL.md").read_text(encoding="utf-8").lower()
        self.assertIn("ruflo is the meta-harness", text)
        self.assertIn("deerflow remains", text)
        self.assertIn("python repository remains the executable evidence source", text)
        self.assertIn("do not enable automatic live broker or exchange order transmission", text)

    def test_bootstraps_require_supported_node_and_seed_only_nonsecret_context(self):
        for relative in ("integrations/ruflo/bootstrap.ps1", "integrations/ruflo/bootstrap.sh"):
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertIn("node", text)
            self.assertIn("20", text)
            self.assertIn("--codex", text)
            self.assertIn("--no-signup", text)
            self.assertIn("orderflow/decisions", text)
            self.assertNotIn("api_key=", text)
            self.assertNotIn("secret=", text)
            self.assertNotIn("password=", text)


if __name__ == "__main__":
    unittest.main()
