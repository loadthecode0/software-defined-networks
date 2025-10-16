from base import BaseSPController

import random
import logging
from typing import List

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, tcp, udp


class LoadBalancedSPController(BaseSPController):
    """Shortest path routing with load-based path selection and TCP/UDP/IP flow installs."""

    def choose_path(self, all_paths: List[List[str]]) -> List[str]:
        """Pick the path with lowest utilization."""
        for path in all_paths:
            print(path, self.graph.path_utilization(path))
        if not all_paths:
            return []
        return min(all_paths, key=lambda p: self.graph.path_utilization(p))

    def install_path_flows(
        self,
        path: List[str],
        src_mac=None,
        dst_mac=None,
        src_ip=None,
        dst_ip=None,
        ip_proto=None,
        src_port=None,
        dst_port=None,
    ):
        """Install bidirectional OpenFlow rules along the given path (supports TCP/UDP/IP)."""
        if not path:
            self.logger.warning("No path to install for %s -> %s", src_mac, dst_mac)
            return

        self.logger.info("Installing flows along path %s for %s -> %s", path, src_mac, dst_mac)
        dpids = [int(s[1:]) for s in path]

        dst_info = self.host_location.get(dst_mac)
        src_info = self.host_location.get(src_mac)
        if not dst_info or not src_info:
            self.logger.warning("Missing host info for flow %s -> %s", src_mac, dst_mac)
            return

        dst_dpid, dst_host_port = dst_info
        src_dpid, src_host_port = src_info
        match_kwargs = dict(eth_src=src_mac, eth_dst=dst_mac)
        if src_ip and dst_ip:
            match_kwargs.update(eth_type=0x0800, ipv4_src=src_ip, ipv4_dst=dst_ip)
        if ip_proto:
            match_kwargs.update(ip_proto=ip_proto)
            if src_port and dst_port:
                if ip_proto == 6:  # TCP
                    match_kwargs.update(tcp_src=src_port, tcp_dst=dst_port)
                elif ip_proto == 17:  # UDP
                    match_kwargs.update(udp_src=src_port, udp_dst=dst_port)

        # --- Forward & reverse flows on all intermediate switches ---
        for i in range(len(dpids) - 1):
            cur = dpids[i]
            nxt = dpids[i + 1]
            dp = self.datapaths.get(cur)
            if not dp:
                continue

            parser = dp.ofproto_parser
            ofproto = dp.ofproto
            out_port = self.adjacency.get(int(cur), {}).get(int(nxt))
            if out_port is None:
                self.logger.warning("No adjacency s%s -> s%s", cur, nxt)
                continue

            # Match for forward direction
            match_kwargs = dict(eth_src=src_mac, eth_dst=dst_mac)
            if src_ip and dst_ip:
                match_kwargs.update(eth_type=0x0800, ipv4_src=src_ip, ipv4_dst=dst_ip)
            if ip_proto:
                match_kwargs.update(ip_proto=ip_proto)
                if src_port and dst_port:
                    if ip_proto == 6:  # TCP
                        match_kwargs.update(tcp_src=src_port, tcp_dst=dst_port)
                    elif ip_proto == 17:  # UDP
                        match_kwargs.update(udp_src=src_port, udp_dst=dst_port)

            match_fwd = parser.OFPMatch(**match_kwargs)
            actions_fwd = [parser.OFPActionOutput(out_port)]
            self.add_flow(dp, 1, match_fwd, actions_fwd)

            # Reverse direction
            if i == 0:
                rev_out = src_host_port
            else:
                prev = dpids[i - 1]
                rev_out = self.adjacency.get(int(cur), {}).get(int(prev))

            if rev_out:
                rev_kwargs = dict(eth_src=dst_mac, eth_dst=src_mac)
                if src_ip and dst_ip:
                    rev_kwargs.update(eth_type=0x0800, ipv4_src=dst_ip, ipv4_dst=src_ip)
                if ip_proto:
                    rev_kwargs.update(ip_proto=ip_proto)
                    if src_port and dst_port:
                        if ip_proto == 6:
                            rev_kwargs.update(tcp_src=dst_port, tcp_dst=src_port)
                        elif ip_proto == 17:
                            rev_kwargs.update(udp_src=dst_port, udp_dst=src_port)

                match_rev = parser.OFPMatch(**rev_kwargs)
                actions_rev = [parser.OFPActionOutput(rev_out)]
                self.add_flow(dp, 1, match_rev, actions_rev)
                # self.graph.update_utilization(cur, nxt, delta=1.0)
                self.graph.update_utilization(f"s{cur}", f"s{nxt}", delta=1.0)

                print(cur)
                print(nxt)
                # print(f"Updated {cur}->{nxt} utilization: {self.graph.utilization.get((cur,nxt))}")
            # self.graph.update_utilization(cur, nxt, delta=1.0)
            self.logger.info("s%s: flows installed out:%s rev_out:%s", cur, out_port, rev_out)

        # --- Final destination switch ---
        final_switch = dpids[-1]
        dp_final = self.datapaths.get(final_switch)
        if dp_final:
            parser = dp_final.ofproto_parser
            ofproto = dp_final.ofproto
            if dst_host_port:
                match_fwd_final = parser.OFPMatch(**match_kwargs)
                actions_fwd_final = [parser.OFPActionOutput(dst_host_port)]
                self.add_flow(dp_final, 1, match_fwd_final, actions_fwd_final)

            if len(dpids) >= 2:
                prev = dpids[-2]
                rev_out = self.adjacency.get(int(final_switch), {}).get(int(prev))
                if rev_out:
                    match_rev_final = parser.OFPMatch(**rev_kwargs)
                    actions_rev_final = [parser.OFPActionOutput(rev_out)]
                    self.add_flow(dp_final, 1, match_rev_final, actions_rev_final)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """PacketIn: parse Ethernet/IP/TCP/UDP, compute path, and install flow."""
        msg = ev.msg
        dp = msg.datapath
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        src, dst = eth.src, eth.dst
        dpid = dp.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if src not in self.host_location:
            self.host_location[src] = (dpid, in_port)
            self.logger.info("Learned host %s at s%s:%s", src, dpid, in_port)

        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        tcp_pkt = pkt.get_protocol(tcp.tcp)
        udp_pkt = pkt.get_protocol(udp.udp)

        src_ip = dst_ip = None
        src_port = dst_port = None
        ip_proto = None

        if ip_pkt:
            src_ip = ip_pkt.src
            dst_ip = ip_pkt.dst
            ip_proto = ip_pkt.proto

            if tcp_pkt:
                src_port, dst_port = tcp_pkt.src_port, tcp_pkt.dst_port
            elif udp_pkt:
                src_port, dst_port = udp_pkt.src_port, udp_pkt.dst_port

        # Flood if destination unknown
        if dst not in self.host_location:
            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
            out = parser.OFPPacketOut(
                datapath=dp,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None,
            )
            dp.send_msg(out)
            return

        dst_dpid, _ = self.host_location[dst]
        src_switch, dst_switch = f"s{dpid}", f"s{dst_dpid}"
        all_paths = self.graph.dijkstra_all_shortest_paths(src_switch, dst_switch)
        path = self.choose_path(all_paths)

        if path:
            self.install_path_flows(
                path,
                src_mac=src,
                dst_mac=dst,
                src_ip=src_ip,
                dst_ip=dst_ip,
                ip_proto=ip_proto,
                src_port=src_port,
                dst_port=dst_port,
            )

        actions = [parser.OFPActionOutput(ofproto.OFPP_TABLE)]
        out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None,
        )
        dp.send_msg(out)
