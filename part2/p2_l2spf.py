from base import BaseSPController

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

import random
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import packet, ethernet, ether_types

class ShortestPathController(BaseSPController):
    """Normal shortest path routing (ECMP random if enabled)"""

    def choose_path(self, all_paths: List[List[str]]) -> List[str]:
        if not all_paths:
            return []

        if self.graph.ecmp:   
            return random.choice(all_paths)
        return all_paths[0] # if not ecmp, choose the first, deterministically

    def install_path_flows(self, path: List[str], src_mac=None, dst_mac=None):
        """
        Install OpenFlow flows for src_mac <-> dst_mac along the given path.
        - path: list of switch names, e.g. ['s1','s2','s4','s6']
        Installs forward (src->dst) and reverse (dst->src) flows on each datapath.
        """
        if not path:
            self.logger.warning("No path to install for %s -> %s", src_mac, dst_mac)
            return

        self.logger.info("Installing flows along path %s for %s -> %s", path, src_mac, dst_mac)

        # convenience: find dpids list from path
        dpids = [int(s[1:]) for s in path]

        # Get host ports (may be needed for final hop)
        dst_info = self.host_location.get(dst_mac)
        src_info = self.host_location.get(src_mac)
        dst_dpid = dst_info[0] if dst_info else None
        dst_host_port = dst_info[1] if dst_info else None
        src_dpid = src_info[0] if src_info else None
        src_host_port = src_info[1] if src_info else None

        # Install forward flows on each hop: for hop i -> i+1 install on dpids[i]
        for i in range(len(dpids) - 1):
            cur = dpids[i]
            nxt = dpids[i + 1]

            dp = self.datapaths.get(cur)
            if not dp:
                self.logger.warning("No datapath object for s%s", cur)
                continue
            parser = dp.ofproto_parser
            ofproto = dp.ofproto

            # out_port toward next switch
            out_port = self.adjacency.get(cur, {}).get(nxt)
            if out_port is None:
                self.logger.warning("No adjacency port for s%s -> s%s; skipping", cur, nxt)
                continue

            # forward match/action on this switch
            match_fwd = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
            actions_fwd = [parser.OFPActionOutput(out_port)]
            self.add_flow(dp, priority=1, match=match_fwd, actions=actions_fwd)

            # reverse on this switch: packets from dst -> src should be sent back toward prev hop
            # find port to previous hop (if i>0), else to src host
            if i == 0:
                # on first hop (source switch), reverse out port should go to host port for src
                rev_out = src_host_port
            else:
                prev = dpids[i - 1]
                rev_out = self.adjacency.get(cur, {}).get(prev)

            if rev_out is None:
                self.logger.warning("No reverse port known for s%s when installing reverse flow", cur)
            else:
                match_rev = parser.OFPMatch(eth_src=dst_mac, eth_dst=src_mac)
                actions_rev = [parser.OFPActionOutput(rev_out)]
                self.add_flow(dp, priority=1, match=match_rev, actions=actions_rev)

            self.logger.info("s%s: installed %s->%s out:%s and reverse out:%s", cur, src_mac, dst_mac, out_port, rev_out)

        # Install rule on the *destination switch* to forward to host port (if not same as previous step)
        final_switch = dpids[-1]
        dp_final = self.datapaths.get(final_switch)
        if dp_final is None:
            self.logger.warning("No datapath for final switch s%s", final_switch)
        else:
            parser = dp_final.ofproto_parser
            ofproto = dp_final.ofproto

            # forward on destination switch: send to host port
            if dst_host_port is None:
                self.logger.warning("No host port known for destination host %s; cannot install final rule", dst_mac)
            else:
                match_fwd_final = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                actions_fwd_final = [parser.OFPActionOutput(dst_host_port)]
                self.add_flow(dp_final, priority=1, match=match_fwd_final, actions=actions_fwd_final)
                self.logger.info("s%s: installed final forward %s->%s out:%s", final_switch, src_mac, dst_mac, dst_host_port)

            # reverse on destination switch: packets from dst->src should go towards previous switch
            if len(dpids) >= 2:
                prev = dpids[-2]
                rev_out = self.adjacency.get(final_switch, {}).get(prev)
                if rev_out is None:
                    self.logger.warning("No reverse port on final switch s%s to previous s%s", final_switch, prev)
                else:
                    match_rev_final = parser.OFPMatch(eth_src=dst_mac, eth_dst=src_mac)
                    actions_rev_final = [parser.OFPActionOutput(rev_out)]
                    self.add_flow(dp_final, priority=1, match=match_rev_final, actions=actions_rev_final)
                    self.logger.info("s%s: installed final reverse %s->%s out:%s", final_switch, dst_mac, src_mac, rev_out)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """PacketIn: compute shortest path, install flows, forward packet"""
        msg = ev.msg
        dp = msg.datapath # current switch
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP: # setup packet, handled separately in base class
            return

        src, dst = eth.src, eth.dst # src and dst hosts
        dpid = dp.id # current switch
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port # controller learns port leading to src from this switch

        # learn host locn (this switch dpid, at this port)
        # self.host_location[src] = (dpid, in_port)
        if src not in self.host_location:
            self.host_location[src] = (dpid, in_port)
            self.logger.info("Learned host %s at s%s:%s", src, dpid, in_port)

        # If packet came from another switch (not directly a host), update adjacency
        # Example: cur_switch = s1, next_switch = s2
        # for neighbor in self.graph.G[f"s{dpid}"]:   # check known neighbors in graph
        #     if neighbor.startswith("s"):           # only care about switches
        #         neighbor_dpid = int(neighbor[1:])
        #         # Record adjacency: this port on cur_switch leads to neighbor
        #         if neighbor_dpid not in self.adjacency[dpid]:
        #             self.adjacency[dpid][neighbor_dpid] = in_port
        #             self.logger.info("Adjacency learned: s%s → s%s via port %s",
        #                             dpid, neighbor_dpid, in_port)

        # if controller doesn't know destination, flood
        if dst not in self.mac_to_port[dpid] or dst not in self.host_location:
            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
            out = parser.OFPPacketOut(
                datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                actions=actions,
                data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
            )
            dp.send_msg(out)
            return

        # here, we know src & dst switches => compute path
        dst_dpid, dst_port = self.host_location[dst]
        src_switch = f"s{dpid}" # current switch
        dst_switch = f"s{dst_dpid}" # switch on which dst host lives
        all_paths = self.graph.dijkstra_all_shortest_paths(src_switch, dst_switch)
        path = self.choose_path(all_paths)

        if path:
            self.install_path_flows(path, src_mac=src, dst_mac=dst)

        # Also send this first packet along the path immediately
        actions = [parser.OFPActionOutput(ofproto.OFPP_TABLE)]
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        dp.send_msg(out)

        

