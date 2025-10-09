#!/usr/bin/env python3
# p3_l3spf.py
# Layer-3 Shortest Path Routing Controller

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, arp, ether_types, icmp
import networkx as nx
import ipaddress
import json
import logging

class L3ShortestPath(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(L3ShortestPath, self).__init__(*args, **kwargs)
        self.logger.setLevel(logging.INFO)

        # Load topology config
        with open("./part3/p3_config.json") as f:
            self.cfg = json.load(f)

        # Build weighted graph
        self.graph = nx.Graph()
        for link in self.cfg["links"]:
            self.graph.add_edge(link["src"], link["dst"], weight=link["cost"])

        self.switches = {s["name"]: s for s in self.cfg["switches"]}
        self.hosts = {h["ip"]: h for h in self.cfg["hosts"]}
        self.datapaths = {}

        self.logger.info("Loaded %d switches and %d links", len(self.switches), len(self.cfg["links"]))

    # --- Helper -------------------------------------------------------------
    def find_router_for_ip(self, ip):
        ip_addr = ipaddress.ip_address(ip)
        for sname, s in self.switches.items():
            for iface in s["interfaces"]:
                if ip_addr in ipaddress.ip_network(iface["subnet"]):
                    return sname
        return None

    def add_flow(self, dp, priority, match, actions):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=inst)
        dp.send_msg(mod)

    def _handle_icmp_request(self, dp, pkt, eth, ip_pkt, in_port):
        """
        Handles an ICMP Echo Request destined for one of the switch's own IPs.
        This should only be called after confirming the packet is for the switch.
        """
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        
        icmp_pkt = pkt.get_protocol(icmp.icmp)
        # We only handle echo requests, not replies or other types.
        if not icmp_pkt or icmp_pkt.type != icmp.ICMP_ECHO_REQUEST:
            return False

        my_ip = ip_pkt.dst
        my_mac = None
        s_name = self.find_router_for_ip(my_ip)
        if not s_name: return False
        
        # Find the MAC for the interface that received the ping
        switch_config = self.switches.get(s_name)
        for iface in switch_config.get("interfaces", []):
            if iface.get("ip") == my_ip:
                my_mac = iface.get("mac")
                break
        
        if not my_mac: return False

        # Construct Echo Reply packet
        p = packet.Packet()
        p.add_protocol(ethernet.ethernet(ethertype=eth.ethertype,
                                          dst=eth.src,
                                          src=my_mac))
        p.add_protocol(ipv4.ipv4(dst=ip_pkt.src,
                                  src=my_ip,
                                  proto=ip_pkt.proto))
        p.add_protocol(icmp.icmp(type_=icmp.ICMP_ECHO_REPLY,
                                  code=icmp.ICMP_ECHO_REPLY_CODE,
                                  csum=0,
                                  data=icmp_pkt.data))
        
        p.serialize()
        actions = [parser.OFPActionOutput(port=in_port)]
        out = parser.OFPPacketOut(datapath=dp,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=p.data)
        dp.send_msg(out)
        self.logger.info("Sent ICMP Echo Reply for %s from %s", my_ip, s_name)
        return True

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        dpid = dp.id
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        self.datapaths[dpid] = dp

        # Table miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)
        self.logger.info("Switch %s connected", dpid)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        # Handle ARP
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt:
            if arp_pkt.opcode == arp.ARP_REQUEST:
                self.handle_arp(dp, in_port, eth, arp_pkt)
            return

        # Handle IPv4
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            self.handle_ipv4(dp, msg, in_port, pkt, eth, ip_pkt)

    def handle_arp(self, dp, in_port, eth, arp_pkt):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        dst_ip = arp_pkt.dst_ip

        # Find the interface with the requested IP and reply
        for s in self.switches.values():
            for i in s["interfaces"]:
                if i["ip"] == dst_ip:
                    e = ethernet.ethernet(dst=eth.src, src=i["mac"], ethertype=ether_types.ETH_TYPE_ARP)
                    a = arp.arp(hwtype=1, proto=0x0800, hlen=6, plen=4, opcode=arp.ARP_REPLY,
                                src_mac=i["mac"], src_ip=dst_ip,
                                dst_mac=eth.src, dst_ip=arp_pkt.src_ip)
                    p = packet.Packet()
                    p.add_protocol(e)
                    p.add_protocol(a)
                    p.serialize()
                    actions = [parser.OFPActionOutput(in_port)]
                    out = parser.OFPPacketOut(datapath=dp,
                                              buffer_id=ofproto.OFP_NO_BUFFER,
                                              in_port=ofproto.OFPP_CONTROLLER,
                                              actions=actions, data=p.data)
                    dp.send_msg(out)
                    self.logger.info("Replied to ARP for %s from %s", dst_ip, i["mac"])
                    return

    ## FIX ##: This entire function has been refactored for clarity and correctness.
    def handle_ipv4(self, dp, msg, in_port, pkt, eth, ip_pkt):
        # First, check if the packet is destined for one of the router's own interfaces
        dst_ip = ip_pkt.dst
        router_name_for_dst = self.find_router_for_ip(dst_ip)
        
        is_for_router = False
        if router_name_for_dst:
            switch_cfg = self.switches[router_name_for_dst]
            for iface in switch_cfg["interfaces"]:
                if iface.get("ip") == dst_ip:
                    is_for_router = True
                    break

        # If it's for one of our interfaces, handle it as a local ICMP request
        if is_for_router:
            if self._handle_icmp_request(dp, pkt, eth, ip_pkt, in_port):
                return # The ICMP request was handled, so we can stop.
        
        # If we get here, the packet is transit traffic that needs to be routed.
        src_ip = ip_pkt.src
        src_router = self.find_router_for_ip(src_ip)
        dst_router = self.find_router_for_ip(dst_ip)

        if not src_router or not dst_router:
            self.logger.warning("Unknown subnet for %s -> %s", src_ip, dst_ip)
            return

        # Calculate and install the path
        path = nx.shortest_path(self.graph, src_router, dst_router, weight="weight")
        self.logger.info(">>> Calculated path for %s -> %s: %s", src_ip, dst_ip, path)
        
        # Install bidirectional flows
        self.install_path(path, dst_ip)
        self.install_path(list(reversed(path)), src_ip)
        
        ## FIX ##: Add PacketOut logic to forward the first packet.
        # This logic sends the original packet on its way after installing the flows.
        if path and len(path) > 1:
            first_switch_name = path[0]
            next_hop_name = path[1]
            
            out_iface = next((iface for iface in self.switches[first_switch_name]["interfaces"] 
                            if iface.get("neighbor") == next_hop_name), None)
            in_iface_next = next((iface for iface in self.switches[next_hop_name]["interfaces"] 
                                if iface.get("neighbor") == first_switch_name), None)

            if out_iface and in_iface_next:
                parser = dp.ofproto_parser
                out_port = int(out_iface["name"].split("eth")[-1])
                src_mac = out_iface["mac"]
                dst_mac = in_iface_next["mac"]

                actions = [
                    parser.OFPActionSetField(eth_src=src_mac),
                    parser.OFPActionSetField(eth_dst=dst_mac),
                    parser.OFPActionDecNwTtl(),
                    parser.OFPActionOutput(out_port)
                ]

                out = parser.OFPPacketOut(datapath=dp,
                                          buffer_id=msg.buffer_id,
                                          in_port=in_port,
                                          actions=actions,
                                          data=msg.data if msg.buffer_id == dp.ofproto.OFP_NO_BUFFER else None)
                dp.send_msg(out)
                self.logger.info("Sent initial packet from %s towards %s", first_switch_name, dst_ip)

    def install_path(self, path, dst_ip):
        """
        Install L3 flows along a path for a given destination IP.
        Handles switch-to-switch hops and final hop to host.
        """
        if len(path) == 0:
            return
            
        for i in range(len(path)):
            curr_switch = path[i]
            dp = next((d for d in self.datapaths.values() if d.id == self.switches[curr_switch]["dpid"]), None)
            if not dp:
                self.logger.warning("Datapath for %s not found!", curr_switch)
                continue
            parser = dp.ofproto_parser

            # Determine next hop: another switch or the final host
            is_last_hop = (i == len(path) - 1)
            
            if is_last_hop:
                # Last hop from switch to destination host
                dst_host_info = self.hosts.get(dst_ip)
                if not dst_host_info: continue

                out_iface = next((iface for iface in self.switches[curr_switch]["interfaces"]
                                  if ipaddress.ip_address(dst_ip) in ipaddress.ip_network(iface["subnet"])), None)
                if not out_iface: continue
                
                out_port = int(out_iface["name"].split("eth")[-1])
                src_mac = out_iface["mac"]
                dst_mac = dst_host_info["mac"]
            else:
                # Intermediate hop from one switch to the next
                next_hop_switch = path[i+1]
                out_iface = next((iface for iface in self.switches[curr_switch]["interfaces"]
                                  if iface.get("neighbor") == next_hop_switch), None)
                in_iface_next = next((iface for iface in self.switches[next_hop_switch]["interfaces"]
                                      if iface.get("neighbor") == curr_switch), None)
                if not out_iface or not in_iface_next: continue
                
                out_port = int(out_iface["name"].split("eth")[-1])
                src_mac = out_iface["mac"]
                dst_mac = in_iface_next["mac"]

            # Create match and actions
            match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=dst_ip)
            actions = [
                parser.OFPActionSetField(eth_src=src_mac),
                parser.OFPActionSetField(eth_dst=dst_mac),
                parser.OFPActionDecNwTtl(),
                parser.OFPActionOutput(out_port)
            ]

            # Install the flow
            self.add_flow(dp, 10, match, actions)
            self.logger.info("Installed L3 flow on %s for dst %s -> port %d (MACs %s -> %s)",
                             curr_switch, dst_ip, out_port, src_mac, dst_mac)