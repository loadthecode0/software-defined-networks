"""
Part 2 Controllers: Shortest Path and Load-Balanced Routing
"""

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
# BaseSPController: common OpenFlow and graph utilities
# ------------------------------------------------------
class BaseSPController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(BaseSPController, self).__init__(*args, **kwargs)
        self.logger.setLevel(logging.INFO)

        # Topology state
        self.graph = {}  # adjacency list
        self.mac_to_port = defaultdict(dict)  # dpid -> {mac: port}
        self.datapaths = {}  # dpid -> datapath
        self.config = {}

        # Optional for load balancing
        self.link_util = defaultdict(float)

        # Config file path (subclasses may override)
        self.config_path = "config.json"

        try:
            self.load_config(self.config_path)
            self.build_graph_from_config()
        except Exception as e:
            self.logger.error("Failed to load config: %s", e)

    # ----------------- OpenFlow setup -----------------

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Install table-miss rule when switch connects"""
        datapath = ev.msg.datapath
        dpid = datapath.id
        self.logger.info("Switch %s connected", dpid)
        self.datapaths[dpid] = datapath

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_timeout=0, hard_timeout=0):
        """Helper to add a flow rule on switch"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst,
                                    idle_timeout=idle_timeout,
                                    hard_timeout=hard_timeout)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst,
                                    idle_timeout=idle_timeout,
                                    hard_timeout=hard_timeout)
        datapath.send_msg(mod)

    def send_packet_out(self, datapath, buffer_id, in_port, actions, data=None):
        """Helper to send PacketOut"""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=buffer_id,
                                  in_port=in_port,
                                  actions=actions,
                                  data=data if buffer_id == ofproto.OFP_NO_BUFFER else None)
        datapath.send_msg(out)

    # ----------------- Config / Graph -----------------

    def load_config(self, path: str):
        """Load config.json (nodes, weight_matrix, ecmp flag)"""
        with open(path, "r") as f:
            self.config = json.load(f)
        self.logger.info("Loaded config: %s", self.config)

    def build_graph_from_config(self):
        """Convert weight_matrix into adjacency list graph"""
        nodes = self.config.get("nodes", [])
        weight_matrix = self.config.get("weight_matrix", [])
        graph = {n: [] for n in nodes}
        n = len(nodes)
        for i in range(n):
            for j in range(n):
                w = weight_matrix[i][j]
                if w and w > 0:
                    graph[nodes[i]].append((nodes[j], w))
        self.graph = graph
        self.logger.info("Built graph: %s", graph)

    def dijkstra_all_shortest_paths(self, src: str, dst: str) -> List[List[str]]:
        """TODO: implement Dijkstra to return shortest path(s)."""
        # Skeleton: return [[]] if no path
        return []

    # ----------------- Subclass hooks -----------------

    def choose_path(self, all_paths: List[List[str]]) -> List[str]:
        """
        Hook: subclasses override this to choose a path.
        Base class defaults to first path.
        """
        return all_paths[0] if all_paths else []

    def install_path_flows(self, path: List[str], src_mac=None, dst_mac=None):
        """
        Install flows along given path.
        TODO: implement actual flow installation using self.datapaths.
        """
        self.logger.info("Installing flows along path: %s", path)

