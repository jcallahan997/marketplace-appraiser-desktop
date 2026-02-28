"""Tests for graph construction."""

from marketplace_appraiser.graph import build_graph


class TestBuildGraph:
    def test_build_without_email(self):
        app = build_graph(send_email=False)
        assert app is not None

    def test_build_with_email(self):
        app = build_graph(send_email=True)
        assert app is not None

    def test_graph_has_all_nodes(self):
        app = build_graph(send_email=True)
        graph = app.get_graph()
        node_ids = set(graph.nodes.keys())
        expected = {
            "scrape_listing",
            "analyze_images",
            "assess_condition",
            "research_market",
            "investigate_seller",
            "assess_price",
            "email_report",
        }
        assert expected.issubset(node_ids)

    def test_graph_without_email_no_email_node(self):
        app = build_graph(send_email=False)
        graph = app.get_graph()
        node_ids = set(graph.nodes.keys())
        assert "email_report" not in node_ids
