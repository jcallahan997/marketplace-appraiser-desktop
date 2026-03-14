"""Outcome feedback tracking for reinforcement learning.

Stores user feedback on appraisal outcomes as JSON files.
Each outcome links back to a run_id and captures what actually happened
after the appraisal — enabling the system to learn from its predictions.

Data flow:
    1. Pipeline produces recommendation + price target (run history)
    2. User provides outcome feedback (this module)
    3. RL training loop consumes (state, action, reward) tuples

Storage: output/feedback/<run_id>.json
"""

import json
import time
from pathlib import Path
from typing import Any, Optional

from marketplace_appraiser.history import HISTORY_DIR, get_run

FEEDBACK_DIR = HISTORY_DIR.parent / "feedback"


def _ensure_dir() -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)


def save_feedback(
    run_id: str,
    *,
    user_action: str,           # "bought", "negotiated", "passed", "still_looking"
    final_price: Optional[float] = None,
    satisfaction: Optional[int] = None,  # 1-5
    price_accuracy: Optional[int] = None,  # 1-5 (how close was the fair value?)
    notes: str = "",
) -> Optional[dict]:
    """Save user feedback for a completed appraisal run.

    Returns the saved feedback record, or None if the run doesn't exist.
    """
    record = get_run(run_id)
    if not record:
        return None

    _ensure_dir()

    # Extract the agent's predictions from the run state
    state = record.get("state", {})
    recommendation = ""
    subject = record.get("report_subject", "") or ""
    if subject.startswith("["):
        end = subject.find("]")
        if end > 0:
            recommendation = subject[1:end].upper()

    feedback = {
        "run_id": run_id,
        "timestamp": time.time(),
        # Agent's predictions
        "agent_recommendation": recommendation,
        "agent_fair_value": state.get("fair_value"),
        "listed_price": state.get("listed_price"),
        "item_name": state.get("item_name", ""),
        "item_type": state.get("item_type", ""),
        # User's actual outcome
        "user_action": user_action,
        "final_price": final_price,
        "satisfaction": satisfaction,
        "price_accuracy": price_accuracy,
        "notes": notes,
        # Computed reward signal
        "reward": _compute_reward(
            recommendation=recommendation,
            fair_value=state.get("fair_value"),
            listed_price=state.get("listed_price"),
            user_action=user_action,
            final_price=final_price,
            satisfaction=satisfaction,
            price_accuracy=price_accuracy,
        ),
        # Feature snapshot for offline training
        "features": _extract_features(state),
    }

    path = FEEDBACK_DIR / f"{run_id}.json"
    path.write_text(json.dumps(feedback, indent=2))
    return feedback


def get_feedback(run_id: str) -> Optional[dict]:
    """Load feedback for a specific run."""
    path = FEEDBACK_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def list_feedback(limit: int = 200) -> list[dict]:
    """List all feedback records, newest first."""
    _ensure_dir()
    records = []
    for path in FEEDBACK_DIR.glob("*.json"):
        try:
            record = json.loads(path.read_text())
            records.append(record)
        except (json.JSONDecodeError, OSError):
            continue
    records.sort(key=lambda r: r.get("timestamp", 0), reverse=True)
    return records[:limit]


def get_training_data() -> list[dict]:
    """Get all feedback as (features, action, reward) tuples for RL training.

    Returns records that have both features and a computed reward.
    """
    all_feedback = list_feedback(limit=10000)
    return [
        {
            "features": fb["features"],
            "action": fb["agent_recommendation"],
            "reward": fb["reward"],
            "run_id": fb["run_id"],
        }
        for fb in all_feedback
        if fb.get("features") and fb.get("reward") is not None
    ]


# ---------------------------------------------------------------------------
# Reward computation
# ---------------------------------------------------------------------------

def _compute_reward(
    recommendation: str,
    fair_value: Any,
    listed_price: Any,
    user_action: str,
    final_price: Optional[float],
    satisfaction: Optional[int],
    price_accuracy: Optional[int],
) -> Optional[float]:
    """Compute a scalar reward from the outcome.

    Reward design:
      - Base: satisfaction score normalized to [-1, 1]
      - Bonus: price accuracy score
      - Bonus: recommendation aligned with user action
      - Penalty: recommendation misaligned with user action

    Returns None if insufficient data to compute reward.
    """
    if satisfaction is None:
        return None

    # Base reward from satisfaction: map 1-5 to [-1, 1]
    reward = (satisfaction - 3) / 2.0  # 1→-1, 2→-0.5, 3→0, 4→0.5, 5→1

    # Price accuracy bonus: map 1-5 to [-0.3, 0.3]
    if price_accuracy is not None:
        reward += (price_accuracy - 3) * 0.15

    # Alignment bonus/penalty
    alignment = _recommendation_alignment(recommendation, user_action)
    reward += alignment * 0.2

    # Price prediction accuracy bonus (if we have both predictions and outcome)
    if final_price and fair_value:
        try:
            fv = float(fair_value)
            fp = float(final_price)
            if fv > 0:
                pct_error = abs(fv - fp) / fv
                # Within 10% → +0.2, within 20% → +0.1, >30% → -0.1
                if pct_error <= 0.10:
                    reward += 0.2
                elif pct_error <= 0.20:
                    reward += 0.1
                elif pct_error > 0.30:
                    reward -= 0.1
        except (ValueError, TypeError):
            pass

    return round(max(-1.5, min(1.5, reward)), 3)


def _recommendation_alignment(recommendation: str, user_action: str) -> float:
    """Score how well the recommendation aligned with the user's action.

    Returns: -1 (misaligned), 0 (neutral), +1 (aligned)
    """
    rec = recommendation.upper()
    act = user_action.lower()

    if rec == "BUY" and act == "bought":
        return 1.0
    if rec == "BUY" and act == "passed":
        return -0.5  # mild penalty — maybe user had other reasons
    if rec == "NEGOTIATE" and act == "negotiated":
        return 1.0
    if rec == "NEGOTIATE" and act == "bought":
        return 0.5  # close enough
    if rec == "PASS" and act == "passed":
        return 1.0
    if rec == "PASS" and act == "bought":
        return -1.0  # agent said pass but user bought — bad signal
    return 0.0


# ---------------------------------------------------------------------------
# Feature extraction for ML
# ---------------------------------------------------------------------------

def _extract_features(state: dict) -> dict:
    """Extract a flat feature dict from pipeline state for ML training.

    These features are the 'state' in the RL formulation.
    """
    features: dict[str, Any] = {}

    # Price features
    try:
        features["listed_price"] = float(state.get("listed_price", 0) or 0)
    except (ValueError, TypeError):
        features["listed_price"] = 0.0

    try:
        features["fair_value"] = float(state.get("fair_value", 0) or 0)
    except (ValueError, TypeError):
        features["fair_value"] = 0.0

    if features["listed_price"] > 0 and features["fair_value"] > 0:
        features["price_ratio"] = features["fair_value"] / features["listed_price"]
    else:
        features["price_ratio"] = 1.0

    # Item features
    features["item_type"] = state.get("item_type", "unknown")
    features["num_images"] = len(state.get("image_paths", []))
    features["num_analyses"] = len(state.get("image_analyses", []))
    features["has_description"] = bool(state.get("description"))
    features["description_length"] = len(state.get("description", "") or "")

    # Vehicle-specific features
    item_fields = state.get("item_fields", {}) or {}
    try:
        features["year"] = int(item_fields.get("year", 0) or 0)
    except (ValueError, TypeError):
        features["year"] = 0
    try:
        features["mileage"] = int(item_fields.get("mileage", 0) or 0)
    except (ValueError, TypeError):
        features["mileage"] = 0

    # Seller features
    features["seller_investigation_length"] = len(
        state.get("seller_investigation", "") or ""
    )

    # Condition features
    features["condition_assessment_length"] = len(
        state.get("condition_assessment", "") or ""
    )

    # Market features
    features["market_research_length"] = len(
        state.get("market_research", "") or ""
    )

    return features
