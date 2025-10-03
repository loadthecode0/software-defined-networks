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



class LoadBalancedSPController(BaseSPController):
    """Load-balanced shortest path: choose path based on utilization"""

    def choose_path(self, all_paths: List[List[str]]) -> List[str]:
        if not all_paths:
            return []
        # Pick path with lowest utilization
        best_path = min(all_paths, key=lambda p: self.graph.path_utilization(p))
        return best_path

    def install_path_flows(self, path: List[str], src_mac=None, dst_mac=None):
        """
        Install flows and update link utilization along chosen path.
        """
        self.logger.info("Installing load-balanced flows along %s for %s → %s", path, src_mac, dst_mac)

        for i in range(len(path) - 1):
            cur_switch = path[i]
            next_switch = path[i+1]

            dp = self.datapaths.get(int(cur_switch[1:]))
            if not dp:
                continue

            parser = dp.ofproto_parser
            ofproto = dp.ofproto

            out_port = None
            for (nbr, w) in self.graph.G[cur_switch].items():
                if nbr == next_switch:
                    out_port = self.graph.G[cur_switch][nbr].get("port", None)
            if out_port is None:
                continue

            match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
            actions = [parser.OFPActionOutput(out_port)]
            self.add_flow(dp, 1, match, actions)

            # Update utilization (simple +1 per flow)
            self.graph.update_utilization(cur_switch, next_switch, delta=1.0)
