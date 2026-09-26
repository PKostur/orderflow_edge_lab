from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from orderflow_edge_lab.jev_research_decision import (
    JevDecisionConfig,
    JevResearchDecisionError,
    decide_sync,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded Jev research-decision layer over a frozen shadow report."
    )
    parser.add_argument("--shadow-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--decision-contract",
        default="config/jev_research_decision_v1.json",
    )
    parser.add_argument("--provider", choices=("auto", "jev", "offline"), default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--min-choice-confidence", type=float, default=None)
    parser.add_argument("--timeout-s", type=float, default=None)
    args = parser.parse_args(argv)

    try:
        shadow = json.loads(Path(args.shadow_report).read_text(encoding="utf-8"))
        contract_path = Path(args.decision_contract)
        contract_bytes = contract_path.read_bytes()
        contract = json.loads(contract_bytes.decode("utf-8"))
        if contract.get("decision_contract_id") != "jev-research-decision-v1":
            raise JevResearchDecisionError("unsupported Jev decision contract")
        provider = args.provider or str(contract["default_provider"])
        model = args.model or str(contract["model"])
        min_choice_confidence = (
            float(args.min_choice_confidence)
            if args.min_choice_confidence is not None
            else float(contract["min_choice_confidence"])
        )
        timeout_s = (
            float(args.timeout_s)
            if args.timeout_s is not None
            else float(contract["timeout_s"])
        )
        result = decide_sync(
            shadow,
            provider=provider,
            config=JevDecisionConfig(
                model=model,
                min_choice_confidence=min_choice_confidence,
                timeout_s=timeout_s,
            ),
        )
        result["decision_contract"] = {
            "decision_contract_id": str(contract["decision_contract_id"]),
            "path": str(contract_path),
            "sha256": sha256(contract_bytes).hexdigest(),
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "decision_id": result["decision_id"],
                    "provider": result["provider"],
                    "provider_resolution": result["provider_resolution"],
                    "model": result["model"],
                    "decision_contract": result["decision_contract"],
                    "selected_action": result["policy"]["selected_action"],
                    "selection_source": result["policy"]["selection_source"],
                    "proposed_action": result["policy"]["proposed_action"],
                    "proposed_action_confidence": result["policy"][
                        "proposed_action_confidence"
                    ],
                    "hard_vetoes": result["policy"]["hard_vetoes"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        JevResearchDecisionError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
