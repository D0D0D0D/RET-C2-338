"""Unit tests — PostProcessNode (ResponseFormat + S-3 APPI presence gate)."""

import pytest

from framework.schemas.agent_status import AgentStatus

from src.constants import APPI_DISCLOSURE_MARKER, APPI_DISCLOSURE_TEXT
from src.nodes.post_process_node import PostProcessNode
from tests.conftest import status_is


class TestPostProcessNode:
    def setup_method(self):
        self.node = PostProcessNode()

    def test_assembles_message(self):
        state = {
            "offer_copy": f"夏物おすすめ\n\n{APPI_DISCLOSURE_TEXT}",
            "promo_copy": "10%OFF",
            "cross_sell": [{"sku": "FOOT-010", "name": "Canvas Sneakers"}],
            "disclosure_attached": True,
        }
        out = self.node.execute(state)
        assert status_is(out["status"], AgentStatus.SUCCESS)
        assert "夏物おすすめ" in out["formatted_output"]["message"]
        assert "Canvas Sneakers" in out["formatted_output"]["message"]

    def test_s3_gate_passes_when_marker_present(self):
        result = {"formatted_output": {"message": f"おすすめ {APPI_DISCLOSURE_MARKER} です"}}
        assert self.node._extra_security_gate_output(result) is result

    def test_s3_gate_raises_when_marker_absent(self):
        result = {"formatted_output": {"message": "開示なしのオファー"}}
        with pytest.raises(RuntimeError, match="APPI"):
            self.node._extra_security_gate_output(result)
