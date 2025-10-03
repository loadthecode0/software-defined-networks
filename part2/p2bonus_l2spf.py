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
# LoadBalancedSPController (bonus)
# ------------------------------------------------------
class LoadBalancedSPController(BaseSPController):
    """Load-balanced shortest path: choose path based on utilization"""

    def choose_path(self, all_paths: List[List[str]]) -> List[str]:
        """
        Override: pick path with lowest utilization.
        (If equal, break ties randomly.)
        """
        if not all_paths:
            return []

        # TODO: implement weighted selection using self.link_util
        return random.choice(all_paths)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """PacketIn: compute load-aware path, install flows, forward"""
        # TODO: same as ShortestPathController but path choice is load-aware
        pass
