"""LangGraph StateGraph assembly for the marketplace appraisal pipeline."""

from langgraph.graph import END, START, StateGraph

from marketplace_appraiser.nodes.condition import assess_condition
from marketplace_appraiser.nodes.email_report import email_report
from marketplace_appraiser.nodes.market import research_market
from marketplace_appraiser.nodes.price import assess_price
from marketplace_appraiser.nodes.scraper import scrape_listing
from marketplace_appraiser.nodes.seller import investigate_seller
from marketplace_appraiser.nodes.vision import analyze_images
from marketplace_appraiser.state import AppraisalState


def build_graph(send_email: bool = False):
    """Build and compile the marketplace appraisal graph.

    Args:
        send_email: If True, appends the email_report node after price assessment.

    Pipeline:
        scrape_listing -> analyze_images -> assess_condition
            -> research_market -> investigate_seller -> assess_price
            -> [email_report] -> END
    """
    graph = StateGraph(AppraisalState)

    graph.add_node("scrape_listing", scrape_listing)
    graph.add_node("analyze_images", analyze_images)
    graph.add_node("assess_condition", assess_condition)
    graph.add_node("research_market", research_market)
    graph.add_node("investigate_seller", investigate_seller)
    graph.add_node("assess_price", assess_price)

    graph.add_edge(START, "scrape_listing")
    graph.add_edge("scrape_listing", "analyze_images")
    graph.add_edge("analyze_images", "assess_condition")
    graph.add_edge("assess_condition", "research_market")
    graph.add_edge("research_market", "investigate_seller")
    graph.add_edge("investigate_seller", "assess_price")

    if send_email:
        graph.add_node("email_report", email_report)
        graph.add_edge("assess_price", "email_report")
        graph.add_edge("email_report", END)
    else:
        graph.add_edge("assess_price", END)

    return graph.compile()
