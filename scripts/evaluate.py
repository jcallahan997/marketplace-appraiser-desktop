#!/usr/bin/env python3
"""Evaluation harness for the marketplace appraiser.

Runs listings through the pipeline, judges output quality with an LLM,
and optionally collects human feedback.

Usage:
    # Evaluate a single listing
    python scripts/evaluate.py https://www.facebook.com/marketplace/item/12345/

    # Evaluate a batch from a file (one URL per line, optional item type after tab)
    python scripts/evaluate.py --batch listings.txt

    # Re-judge a previous run (skip the appraisal, just re-score)
    python scripts/evaluate.py --rejudge output/evals/eval_20260301_123456.json

    # Include human feedback prompts
    python scripts/evaluate.py --human https://www.facebook.com/marketplace/item/12345/

    # Use vehicle appraiser instead of marketplace appraiser
    python scripts/evaluate.py --vehicle https://www.facebook.com/marketplace/item/12345/
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVAL_DIR = Path("output/evals")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "claude-opus-4-20250514")

JUDGE_RUBRIC = """\
You are an expert evaluator of marketplace listing appraisals. Score the
following appraisal on these criteria (1-5 each, where 5 is excellent):

1. **ACCURACY** — Does the price assessment match the evidence? Is the fair
   value estimate reasonable given condition, market data, and comparable
   listings? Are there any factual errors?

2. **COMPLETENESS** — Does it cover: price evaluation, fair value, clear
   recommendation (BUY/NEGOTIATE/PASS), negotiation target (if applicable),
   confidence level, seller trust assessment, flip risk, and a summary?

3. **JUDGEMENT** — Is the recommendation appropriate? Would a savvy buyer
   agree with BUY vs NEGOTIATE vs PASS? Does it balance risk factors
   (flip risk, seller trust, condition issues, safety recalls) correctly?

4. **ACTIONABILITY** — Can the buyer act on this? Does it give specific
   numbers, specific things to check, and clear next steps?

5. **CALIBRATION** — Is the confidence level appropriate? Does HIGH confidence
   match strong evidence, and LOW match uncertainty? Are caveats included
   where needed?

Also provide:
- **MAJOR_ISSUES**: List any serious problems (wrong recommendation,
  missed red flags, factual errors). Empty list if none.
- **MINOR_ISSUES**: List any small improvements. Empty list if none.
- **OVERALL**: 1-5 composite score.

ITEM: {item_name}
LISTED PRICE: ${listed_price}
ITEM TYPE: {item_type}

CONDITION REPORT:
{condition_report}

MARKET ANALYSIS:
{market_analysis}

FLIP SIGNALS:
{flip_signals}

SAFETY INFO:
{safety_info}

--- APPRAISAL BEING EVALUATED ---
{price_assessment}
--- END APPRAISAL ---

Output valid JSON only:
{{
  "accuracy": <1-5>,
  "completeness": <1-5>,
  "judgement": <1-5>,
  "actionability": <1-5>,
  "calibration": <1-5>,
  "overall": <1-5>,
  "major_issues": ["issue1", ...],
  "minor_issues": ["issue1", ...],
  "reasoning": "<2-3 sentence explanation of overall score>"
}}"""


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------

def judge_appraisal(result: dict) -> dict:
    """Use a strong LLM to score an appraisal result."""
    import anthropic

    client = anthropic.Anthropic()

    flip_signals = result.get("flip_signals", [])
    flip_text = "\n".join(flip_signals) if flip_signals else "None detected"

    prompt = JUDGE_RUBRIC.format(
        item_name=result.get("item_name", "Unknown"),
        listed_price=result.get("listed_price", "Unknown"),
        item_type=result.get("item_type", "unknown"),
        condition_report=result.get("condition_report", "(not available)"),
        market_analysis=result.get("market_analysis", "(not available)"),
        flip_signals=flip_text,
        safety_info=result.get("safety_info", "None"),
        price_assessment=result.get("price_assessment", "(empty)"),
    )

    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=JUDGE_MODEL,
                max_tokens=1024,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                return json.loads(json_match.group())
            return {"error": "No JSON in judge response", "raw": text}
        except Exception as e:
            if attempt == MAX_RETRIES:
                return {"error": str(e)}
            time.sleep(2 ** attempt)

    return {"error": "Judge failed after retries"}


# ---------------------------------------------------------------------------
# Human feedback
# ---------------------------------------------------------------------------

def collect_human_feedback() -> dict:
    """Prompt the user for optional human scores."""
    print("\n--- HUMAN EVALUATION (press Enter to skip any) ---")

    scores = {}
    for criterion in ["accuracy", "completeness", "judgement", "actionability", "calibration", "overall"]:
        val = input(f"  {criterion} (1-5): ").strip()
        if val:
            try:
                scores[criterion] = int(val)
            except ValueError:
                pass

    notes = input("  Notes (optional): ").strip()
    if notes:
        scores["notes"] = notes

    return scores if scores else {}


# ---------------------------------------------------------------------------
# Run a single listing through the appraiser
# ---------------------------------------------------------------------------

def run_appraisal(url: str, item_type: str = None, use_vehicle: bool = False) -> dict:
    """Run one listing through the appraisal pipeline and return the full state."""
    start = time.time()

    if use_vehicle:
        from vehicle_appraiser.graph import build_graph
        app = build_graph(send_email=False)
        initial_state = {"listing_url": url}
    else:
        from marketplace_appraiser.graph import build_graph
        app = build_graph(send_email=False)
        initial_state = {"listing_url": url}
        if item_type:
            initial_state["item_type"] = item_type

    result = app.invoke(initial_state)
    elapsed = time.time() - start

    # Convert to plain dict for serialization
    out = dict(result)
    out["_eval_meta"] = {
        "url": url,
        "item_type_override": item_type,
        "engine": "vehicle" if use_vehicle else "marketplace",
        "elapsed_seconds": round(elapsed, 1),
        "timestamp": datetime.now().isoformat(),
    }

    return out


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def make_serializable(obj):
    """Convert non-JSON-serializable types."""
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    return str(obj)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Evaluate marketplace appraisals")
    parser.add_argument("url", nargs="?", help="Single listing URL")
    parser.add_argument("--batch", metavar="FILE", help="File with URLs (one per line, optional tab-separated item type)")
    parser.add_argument("--rejudge", metavar="FILE", help="Re-judge a previous eval JSON")
    parser.add_argument("--human", action="store_true", help="Prompt for human scores after each listing")
    parser.add_argument("--vehicle", action="store_true", help="Use vehicle appraiser instead of marketplace")
    parser.add_argument("--item-type", metavar="TYPE", help="Item type for marketplace appraiser")
    args = parser.parse_args()

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- Re-judge mode ---
    if args.rejudge:
        print(f"Re-judging {args.rejudge}...")
        with open(args.rejudge) as f:
            data = json.load(f)

        results = data if isinstance(data, list) else [data]
        for r in results:
            print(f"\n  Judging: {r.get('item_name', r.get('_eval_meta', {}).get('url', '?'))}...")
            r["_judge"] = judge_appraisal(r)
            print(f"  Overall: {r['_judge'].get('overall', '?')}/5")
            if args.human:
                r["_human"] = collect_human_feedback()

        out_path = Path(args.rejudge).with_suffix(".rejudged.json")
        with open(out_path, "w") as f:
            json.dump(make_serializable(results), f, indent=2)
        print(f"\nSaved to {out_path}")
        _print_summary(results)
        return

    # --- Build listing queue ---
    listings = []
    if args.batch:
        with open(args.batch) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                url = parts[0].strip()
                itype = parts[1].strip() if len(parts) > 1 else None
                listings.append((url, itype))
    elif args.url:
        listings.append((args.url, args.item_type))
    else:
        parser.print_help()
        sys.exit(1)

    print(f"\nEvaluating {len(listings)} listing(s)...")
    print(f"Judge model: {JUDGE_MODEL}")
    if args.human:
        print("Human feedback: ENABLED")
    print()

    # --- Run and evaluate ---
    results = []
    for i, (url, itype) in enumerate(listings, 1):
        print(f"{'='*60}")
        print(f"LISTING {i}/{len(listings)}: {url}")
        if itype:
            print(f"  Item type: {itype}")
        print(f"{'='*60}")

        try:
            result = run_appraisal(url, item_type=itype, use_vehicle=args.vehicle)

            # Judge
            print(f"\n  Judging with {JUDGE_MODEL}...")
            result["_judge"] = judge_appraisal(result)
            judge = result["_judge"]
            if "error" not in judge:
                print(f"  Scores: accuracy={judge.get('accuracy')}, "
                      f"judgement={judge.get('judgement')}, "
                      f"overall={judge.get('overall')}/5")
                if judge.get("major_issues"):
                    print(f"  Major issues:")
                    for issue in judge["major_issues"]:
                        print(f"    - {issue}")
            else:
                print(f"  Judge error: {judge['error']}")

            # Human feedback
            if args.human:
                print(f"\n{result.get('price_assessment', '(no assessment)')}")
                result["_human"] = collect_human_feedback()

            results.append(result)

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "_eval_meta": {"url": url, "error": str(e),
                               "timestamp": datetime.now().isoformat()},
            })

        # Save incrementally
        eval_path = EVAL_DIR / f"eval_{timestamp}.json"
        with open(eval_path, "w") as f:
            json.dump(make_serializable(results), f, indent=2)

    # --- Summary ---
    print(f"\n{'='*60}")
    print("EVALUATION SUMMARY")
    print(f"{'='*60}")
    _print_summary(results)
    print(f"\nFull results saved to: {eval_path}")


def _print_summary(results: list[dict]):
    """Print a summary table of all evaluations."""
    print(f"\n{'Item':<40} {'Rec':<10} {'Price':<10} {'Overall':<8} {'Accuracy':<9} {'Judgement':<9}")
    print("-" * 96)

    overall_scores = []
    for r in results:
        meta = r.get("_eval_meta", {})
        judge = r.get("_judge", {})

        name = r.get("item_name", meta.get("url", "?"))[:38]
        price = r.get("listed_price", "?")
        assessment = r.get("price_assessment", "")

        # Extract recommendation from assessment
        rec = "?"
        for keyword in ["PASS", "NEGOTIATE", "BUY"]:
            if keyword in assessment.upper():
                rec = keyword
                break

        overall = judge.get("overall", "?")
        accuracy = judge.get("accuracy", "?")
        judgement = judge.get("judgement", "?")

        if isinstance(overall, (int, float)):
            overall_scores.append(overall)

        price_str = f"${price:,.0f}" if isinstance(price, (int, float)) else str(price)
        print(f"{name:<40} {rec:<10} {price_str:<10} {overall}/5     {accuracy}/5      {judgement}/5")

        human = r.get("_human", {})
        if human and human.get("overall"):
            print(f"  {'(human)':<38} {'':10} {'':10} {human['overall']}/5")

    if overall_scores:
        avg = sum(overall_scores) / len(overall_scores)
        print(f"\n{'Average':<40} {'':10} {'':10} {avg:.1f}/5")


if __name__ == "__main__":
    main()
