# -*- coding: utf-8 -*-
"""评测集回归：企业级 Agent 的"验收标准"（18 个用例，4 类）。

两种模式:
  --retrieval-only  只测检索命中率（离线可跑，CI 里用）
  默认             全链路：检索 + LLM 生成（需要 MISTRAL_API_KEY）

通过标准: 检索命中率 100%（must_hit 全命中）；LLM 模式输出含
must_contain_any 关键词之一。结果打印明细 + 汇总分数。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.store import retrieve  # noqa: E402

EVAL_PATH = Path(__file__).resolve().parents[1] / "app" / "evals" / "eval_set.jsonl"


def load_cases() -> list[dict]:
    return [json.loads(line) for line in EVAL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_retrieval(case: dict) -> tuple[bool, str]:
    if not case["must_hit"]:
        return True, "no-retrieval-required"
    hits = retrieve(case["question"], top_k=4)
    files = {h["file"] for h in hits}
    missing = [f for f in case["must_hit"] if f not in files]
    return not missing, ("hit: " + ", ".join(sorted(files))) if not missing else f"MISS: {missing}"


def check_full(case: dict) -> tuple[bool, str]:
    from app.guardrails.pii import detect_injection, mask_pii
    injected, _ = detect_injection(case["question"])
    if injected:
        return "must_contain_any" in case and case["category"] == "out_of_scope", "injection-blocked"
    from app.rag.service import answer
    result = answer(mask_pii(case["question"]))
    text = result["answer"]
    ok = any(k in text for k in case["must_contain_any"])
    return ok, text[:80].replace("\n", " ")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieval-only", action="store_true")
    args = ap.parse_args()

    cases = load_cases()
    passed = 0
    for case in cases:
        ok, detail = check_retrieval(case) if args.retrieval_only else check_full(case)
        passed += ok
        mark = "✅" if ok else "❌"
        print(f"{mark} [{case['category']:12s}] {case['id']}: {detail}")
    print(f"\n{passed}/{len(cases)} passed ({passed/len(cases)*100:.0f}%)")
    sys.exit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
