from base import ShortestPathController

import json
import random
import logging
from collections import defaultdict
from typing import Dict, List, Tuple

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types

# ------------------------------------------------------
# ShortestPathController (normal with optional ECMP)
# ------------------------------------------------------
class ShortestPathController(BaseSPController):
    """Normal shortest path routing (ECMP random if enabled)"""

    def choose_path(self, all_paths: List[List[str]]) -> List[str]:
        if not all_paths:
            return []
        if self.config.get("ecmp", False):
            return random.choice(all_paths)
        return all_paths[0]

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """PacketIn: compute shortest path, install flows, forward"""
        # TODO: same flow as Part 1 but compute/choose path before installing flows
        pass

