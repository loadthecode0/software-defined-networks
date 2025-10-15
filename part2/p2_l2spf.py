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
from ryu.lib.packet import ipv4, tcp

import time

class ShortestPathController(BaseSPController):
    """Normal shortest path routing (ECMP random if enabled)"""

    def choose_path(self, all_paths: List[List[str]]) -> List[str]:
        if not all_paths:
            return []

        if self.graph.ecmp:   
            return random.choice(all_paths)
        return all_paths[0] # if not ecmp, choose the first, deterministically

    def install_path_flows(
        self,
        path: List[str],
        src_mac=None,
        dst_mac=None,
        src_ip=None,
        dst_ip=None,
        src_port=None,
        dst_port=None
        ):
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

        # Get host switches and ports (may be needed for final hop)
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
            # match_fwd = parser.OFPMatch(eth_type=0x0800,eth_src=src_mac, eth_dst=dst_mac, ip_proto=6, tcp_src=src_port, tcp_dst=dst_port)
            # Base L2 match
            fwd_match_kwargs = dict(eth_src=src_mac, eth_dst=dst_mac)

            # Add IP and TCP fields if present
            if src_ip and dst_ip:
                fwd_match_kwargs.update(eth_type=0x0800, ipv4_src=src_ip, ipv4_dst=dst_ip)
            if src_port and dst_port:
                fwd_match_kwargs.update(ip_proto=6, tcp_src=src_port, tcp_dst=dst_port)

            match_fwd = parser.OFPMatch(**fwd_match_kwargs)

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
                # match_rev = parser.OFPMatch(eth_type=0x0800,eth_src=dst_mac, eth_dst=src_mac, ip_proto=6, tcp_src=dst_port, tcp_dst=src_port)
                match_rev_kwargs = dict(eth_src=dst_mac, eth_dst=src_mac)
                if src_ip and dst_ip:
                    match_rev_kwargs.update(eth_type=0x0800, ipv4_src=dst_ip, ipv4_dst=src_ip)
                if src_port and dst_port:
                    match_rev_kwargs.update(ip_proto=6, tcp_src=dst_port, tcp_dst=src_port)

                match_rev = parser.OFPMatch(**match_rev_kwargs)
                actions_rev = [parser.OFPActionOutput(rev_out)]
                self.add_flow(dp, priority=1, match=match_rev, actions=actions_rev)

            self.logger.info("s%s: installed %s->%s out:%s and reverse out:%s", cur, src_mac, dst_mac, out_port, rev_out)
            # time.sleep(1)

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
                # match_fwd_final = parser.OFPMatch(eth_type=0x0800,eth_src=src_mac, eth_dst=dst_mac, ip_proto=6, tcp_src=src_port, tcp_dst=dst_port)
                match_fwd_final = parser.OFPMatch(**fwd_match_kwargs)
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
                    # match_rev_final = parser.OFPMatch(eth_type=0x0800,eth_src=dst_mac, eth_dst=src_mac, ip_proto=6, tcp_src=dst_port, tcp_dst=src_port)
                    match_rev_kwargs = dict(eth_src=dst_mac, eth_dst=src_mac)
                    if src_ip and dst_ip:
                        match_rev_kwargs.update(eth_type=0x0800, ipv4_src=dst_ip, ipv4_dst=src_ip)
                    if src_port and dst_port:
                        match_rev_kwargs.update(ip_proto=6, tcp_src=dst_port, tcp_dst=src_port)

                    match_rev_final = parser.OFPMatch(**match_rev_kwargs)
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

        # after parsing ethernet
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        # ip_pkt=None
        tcp_pkt = pkt.get_protocol(tcp.tcp)

        # if not tcp_pkt:
        # #     # don't install path yet; just flood until TCP is seen
        # #     actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        # #     self.logger.info("[FLOOD]")
        # #     out = parser.OFPPacketOut(
        # #         datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
        # #         actions=actions, data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        # #     )
        # #     dp.send_msg(out)
        #     return

        src_ip = dst_ip = None
        src_port = dst_port = None

        if ip_pkt:
            self.logger.info("IP detected")
            src_ip = ip_pkt.src
            dst_ip = ip_pkt.dst

        if tcp_pkt:
            self.logger.info("TCP detected")
            src_port = tcp_pkt.src_port
            dst_port = tcp_pkt.dst_port

        src, dst = eth.src, eth.dst # src and dst hosts
        dpid = dp.id # current switch
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port # controller learns port leading to src from this switch

        # learn host locn (this switch dpid, at this port)
        # self.host_location[src] = (dpid, in_port)
        if src not in self.host_location:
            self.host_location[src] = (dpid, in_port)
            self.logger.info("Learned host %s at s%s:%s", src, dpid, in_port)

        # if controller doesn't know destination, flood
        if dst not in self.mac_to_port[dpid] or dst not in self.host_location:
            self.logger.debug("[FLOOD] Unknown destination %s (src=%s, s%s)", dst, src, dpid)
            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
            out = parser.OFPPacketOut(
                datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                actions=actions,
                data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
            )
            dp.send_msg(out)
            return

        # here, we know src & dst switches => compute path
        dst_dpid, dst_host_port = self.host_location[dst]
        src_switch = f"s{dpid}" # current switch
        dst_switch = f"s{dst_dpid}" # switch on which dst host lives
        all_paths = self.graph.dijkstra_all_shortest_paths(src_switch, dst_switch)
        path = self.choose_path(all_paths)

        if path:
            self.logger.info(f"[INSTALL] from switch {dpid}")
            # self.install_path_flows(path, src_mac=src, dst_mac=dst)
            self.install_path_flows(
                path,
                src_mac=src,
                dst_mac=dst,
                src_ip=src_ip,
                dst_ip=dst_ip,
                src_port=src_port,
                dst_port=dst_port
            )

        # Also send this first packet along the path immediately
        actions = [parser.OFPActionOutput(ofproto.OFPP_TABLE)]
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        dp.send_msg(out)

        

