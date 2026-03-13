"""LangGraph StateGraph assembly for the marketplace appraisal pipeline."""

from typing import Callable, Optional

from langgraph.graph import END, START, StateGraph

from marketplace_appraiser.nodes.condition import assess_condition
from marketplace_appraiser.nodes.email_report import email_report
from marketplace_appraiser.nodes.market import research_market
from marketplace_appraiser.nodes.price import assess_price
from marketplace_appraiser.nodes.scraper import scrape_listing
from marketplace_appraiser.nodes.seller import investigate_seller
from marketplace_appraiser.nodes.vision import analyze_images
from marketplace_appraiser.state import AppraisalState

# Node names and their step numbers (1-indexed, matching STEP N: prints)
PIPELINE_NODES = [
    ("scrape_listing", 1),
    ("analyze_images", 2),
    ("assess_condition", 3),
    ("research_market", 4),
    ("investigate_seller", 5),
    ("assess_price", 6),
    ("email_report", 7),
]

# Human-readable step labels for the dashboard
STEP_LABELS = {
    "scrape_listing": "Scrape Listing",
    "analyze_images": "Analyze Images",
    "assess_condition": "Assess Condition",
    "research_market": "Research Market",
    "investigate_seller": "Investigate Seller",
    "assess_price": "Assess Price",
    "email_report": "Build Email Report",
}


def _wrap_node(
    node_fn,
    node_name: str,
    step_num: int,
    on_node_start: Optional[Callable] = None,
    on_node_end: Optional[Callable] = None,
):
    """Wrap a node function to emit start/end callbacks."""
    def wrapped(state):
        if on_node_start:
            on_node_start(node_name, step_num)
        result = node_fn(state)
        if on_node_end:
            on_node_end(node_name, step_num)
        return result
    wrapped.__name__ = node_fn.__name__
    return wrapped


def build_graph(
    send_email: bool = False,
    on_node_start: Optional[Callable] = None,
    on_node_end: Optional[Callable] = None,
):
    """Build and compile the marketplace appraisal graph.

    Args:
        send_email: If True, appends the email_report node after price assessment.
        on_node_start: Optional callback(node_name, step_number) called before each node.
        on_node_end: Optional callback(node_name, step_number) called after each node.

    Pipeline:
        scrape_listing -> analyze_images -> assess_condition
            -> research_market -> investigate_seller -> assess_price
            -> [email_report] -> END
    """
    graph = StateGraph(AppraisalState)

    node_fns = {
        "scrape_listing": scrape_listing,
        "analyze_images": analyze_images,
        "assess_condition": assess_condition,
        "research_market": research_market,
        "investigate_seller": investigate_seller,
        "assess_price": assess_price,
    }

    for node_name, step_num in PIPELINE_NODES[:6]:
        fn = node_fns[node_name]
        if on_node_start or on_node_end:
            fn = _wrap_node(fn, node_name, step_num, on_node_start, on_node_end)
        graph.add_node(node_name, fn)

    graph.add_edge(START, "scrape_listing")
    graph.add_edge("scrape_listing", "analyze_images")
    graph.add_edge("analyze_images", "assess_condition")
    graph.add_edge("assess_condition", "research_market")
    graph.add_edge("research_market", "investigate_seller")
    graph.add_edge("investigate_seller", "assess_price")

    if send_email:
        fn = email_report
        if on_node_start or on_node_end:
            fn = _wrap_node(fn, "email_report", 7, on_node_start, on_node_end)
        graph.add_node("email_report", fn)
        graph.add_edge("assess_price", "email_report")
        graph.add_edge("email_report", END)
    else:
        graph.add_edge("assess_price", END)

    return graph.compile()
