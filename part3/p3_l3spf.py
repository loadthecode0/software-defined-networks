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

    # --- Switch connect -----------------------------------------------------



    def add_flow(self, dp, priority, match, actions):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=inst)
        dp.send_msg(mod)

    def _handle_icmp_request(self, dp, pkt, eth, ip_pkt, in_port):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        
        # MODIFIED: Get the ICMP protocol from the main 'pkt' object
        icmp_pkt = pkt.get_protocol(icmp.icmp)
        if not icmp_pkt or icmp_pkt.type != icmp.ICMP_ECHO_REQUEST:
            return False

        my_ip = ip_pkt.dst
        my_mac = None
        s_name = self.find_router_for_ip(my_ip)
        if not s_name: return False
        
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
    # # self switch reply 
    # def _handle_icmp_request(self, dp, eth, ip_pkt, in_port):
    #     """
    #     Handles an ICMP Echo Request destined for the switch's own IP.
    #     Constructs and sends an ICMP Echo Reply.
    #     """
    #     parser = dp.ofproto_parser
    #     ofproto = dp.ofproto
        
    #     # Check if it's an Echo Request
    #     icmp_pkt = ip_pkt.get_protocol(icmp.icmp)
    #     if not icmp_pkt or icmp_pkt.type != 8: # 8 is Echo Request
    #         return False

    #     # Find the switch interface IP that was the target of the ping
    #     my_ip = ip_pkt.dst
    #     my_mac = None
    #     s_name = self.find_router_for_ip(my_ip)
    #     if not s_name: return False
        
    #     switch_config = self.switches.get(s_name)
    #     for iface in switch_config.get("interfaces", []):
    #         if iface.get("ip") == my_ip:
    #             my_mac = iface.get("mac")
    #             break
        
    #     if not my_mac: return False

    #     # Construct Echo Reply packet
    #     p = packet.Packet()
    #     p.add_protocol(ethernet.ethernet(ethertype=eth.ethertype,
    #                                       dst=eth.src,
    #                                       src=my_mac))
    #     p.add_protocol(ipv4.ipv4(dst=ip_pkt.src,
    #                              src=my_ip,
    #                              proto=ip_pkt.proto))
    #     p.add_protocol(icmp_pkt.__class__(type_=0, # 0 is Echo Reply
    #                                       code=0,
    #                                       csum=0,
    #                                       data=icmp_pkt.data))
        
    #     # Send the reply via PacketOut
    #     p.serialize()
    #     actions = [parser.OFPActionOutput(port=in_port)]
    #     out = parser.OFPPacketOut(datapath=dp,
    #                               buffer_id=ofproto.OFP_NO_BUFFER,
    #                               in_port=ofproto.OFPP_CONTROLLER,
    #                               actions=actions,
    #                               data=p.data)
    #     dp.send_msg(out)
    #     self.logger.info("Sent ICMP Echo Reply for %s from %s", my_ip, s_name)
    #     return True







    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        dpid = dp.id
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        self.datapaths[dpid] = dp

        # Table miss
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)
        self.logger.info("Switch %s connected", dpid)

    # --- Packet-in handler --------------------------------------------------
# REPLACE this entire function
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
            # MODIFIED: Pass the full 'pkt' object
            self.handle_ipv4(dp, in_port, pkt, eth, ip_pkt)
    # @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    # def packet_in_handler(self, ev):
    #     msg = ev.msg
    #     dp = msg.datapath
    #     dpid = dp.id
    #     parser = dp.ofproto_parser
    #     ofproto = dp.ofproto
    #     in_port = msg.match["in_port"]

    #     pkt = packet.Packet(msg.data)
    #     eth = pkt.get_protocol(ethernet.ethernet)

    #     if eth.ethertype == ether_types.ETH_TYPE_LLDP:
    #         return

    #     # Handle ARP
    #     arp_pkt = pkt.get_protocol(arp.arp)
    #     if arp_pkt:
    #         if arp_pkt.opcode == arp.ARP_REQUEST:
    #             self.handle_arp(dp, in_port, eth, arp_pkt)
    #         return

    #     # Handle IPv4
    #     ip_pkt = pkt.get_protocol(ipv4.ipv4)
    #     if ip_pkt:
    #         self.handle_ipv4(dp, in_port, msg, eth, ip_pkt)

    # --- ARP reply ----------------------------------------------------------
    def handle_arp(self, dp, in_port, eth, arp_pkt):
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        dst_ip = arp_pkt.dst_ip

        for s in self.switches.values():
            for i in s["interfaces"]:
                if i["ip"] == dst_ip:
                    # send reply
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

    # --- IPv4 routing -------------------------------------------------------
    # def handle_ipv4(self, dp, in_port, msg, eth, ip_pkt):
    #     if self._handle_icmp_request(dp, eth, ip_pkt, in_port):
    #         return # If it was handled, we are done.
    #     src_ip, dst_ip = ip_pkt.src, ip_pkt.dst

    #     src_router = self.find_router_for_ip(src_ip)
    #     dst_router = self.find_router_for_ip(dst_ip)

    #     if not src_router or not dst_router:
    #         self.logger.warning("Unknown subnet for %s -> %s", src_ip, dst_ip)
    #         return

    #     path = nx.shortest_path(self.graph, src_router, dst_router, weight="weight")
    #     self.logger.info("Path %s -> %s : %s", src_ip, dst_ip, path)

    #     # Install bidirectional flows
    #     self.install_path(path, ip_pkt.dst)
    #     self.install_path(list(reversed(path)), ip_pkt.src)

    def handle_ipv4(self, dp, in_port, pkt, eth, ip_pkt):
        # Check if the packet is an ICMP request for the switch itself
        # MODIFIED: Pass the full 'pkt' object
        if self._handle_icmp_request(dp, pkt, eth, ip_pkt, in_port):
            return

        src_ip, dst_ip = ip_pkt.src, ip_pkt.dst

        src_router = self.find_router_for_ip(src_ip)
        dst_router = self.find_router_for_ip(dst_ip)

        if not src_router or not dst_router:
            self.logger.warning("Unknown subnet for %s -> %s", src_ip, dst_ip)
            return

        path = nx.shortest_path(self.graph, src_router, dst_router, weight="weight")
        self.logger.info(">>> Calculated path for %s -> %s: %s", src_ip, dst_ip, path)
        
        # Install bidirectional flows
        self.install_path(path, ip_pkt.dst)
        self.install_path(list(reversed(path)), ip_pkt.src)


    def install_path(self, path, dst_ip):
        """
        Install L3 flows along a path for a given destination IP.
        Handles switch-to-switch hops and final hop to host.
        """
        for i in range(len(path)):
            curr_switch = path[i]
            # dp = next((d for d in self.datapaths.values()
            #         if d.id == int(self.switches[curr_switch]["dpid"]), None))
            dp = next((d for d in self.datapaths.values()
                      if d.id == int(self.switches[curr_switch]["dpid"])), None)

            if not dp:
                continue
            parser = dp.ofproto_parser

            # Determine next hop
            if i < len(path) - 1:
                next_hop = path[i + 1]
            else:
                next_hop = dst_ip  # final hop to host

            # --- Host-facing hop (final switch only) ---
            if (i == len(path) - 1) and (dst_ip in self.hosts):
                host_entry = self.hosts[dst_ip]
                host_name = host_entry["name"]
                dst_host_mac = host_entry["mac"]

                out_iface = next(
                    (iface for iface in self.switches[curr_switch]["interfaces"]
                    if iface.get("neighbor") == host_name),
                    None
                )

                if not out_iface:
                    self.logger.warning("No host-facing interface on %s for host %s (%s)",
                                        curr_switch, host_name, dst_ip)
                    continue

                out_port = int(out_iface["name"].split("eth")[-1])
                src_mac = out_iface["mac"]
                dst_mac = dst_host_mac

                self.logger.info("Host-facing port on %s for %s is %s",
                                curr_switch, dst_ip, out_iface["name"])

            # --- Switch-to-switch hops ---
            else:
                out_iface = next(
                    (iface for iface in self.switches[curr_switch]["interfaces"]
                    if iface.get("neighbor") == next_hop),
                    None)
                in_iface_next = next(
                    (iface for iface in self.switches[next_hop]["interfaces"]
                    if iface.get("neighbor") == curr_switch),
                    None)

                if not out_iface or not in_iface_next:
                    self.logger.warning("Missing inter-switch iface for %s -> %s",
                                        curr_switch, next_hop)
                    continue

                out_port = int(out_iface["name"].split("eth")[-1])
                src_mac = out_iface["mac"]
                dst_mac = in_iface_next["mac"]

            # Install flow
            match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=dst_ip)
            actions = [
                parser.OFPActionSetField(eth_src=src_mac),
                parser.OFPActionSetField(eth_dst=dst_mac),
                parser.OFPActionDecNwTtl(),
                parser.OFPActionOutput(out_port)
            ]

            self.add_flow(dp, 10, match, actions)
            self.logger.info("Installed L3 flow on %s for dst %s -> port %d (MACs %s -> %s)",
                            curr_switch, dst_ip, out_port, src_mac, dst_mac)


    # def install_path(self, path, dst_ip):
    #     """
    #     Install L3 flows along a path for a given destination IP.
    #     Handles switch-to-switch hops and final hop to host.
    #     """
    #     for i in range(len(path)):
    #         curr_switch = path[i]
    #         dp = next((d for d in self.datapaths.values() if d.id == self.switches[curr_switch]["dpid"]), None)
    #         if not dp:
    #             continue
    #         parser = dp.ofproto_parser

    #         # Determine next hop
    #         if i < len(path) - 1:
    #             next_hop = path[i+1]
    #         else:
    #             next_hop = dst_ip  # final hop to host

    #         # Determine output port and MAC addresses
    #         if dst_ip in self.hosts:
    #             # Final hop to host
    #             host_entry = self.hosts[dst_ip]
    #             host_name = host_entry["name"]
    #             dst_host_mac = host_entry["mac"]

    #             # Find interface facing the host (neighbor == host name)
    #             out_iface = next(
    #                 (iface for iface in self.switches[curr_switch]["interfaces"]
    #                  if iface.get("neighbor") == host_name),
    #                 None
    #             )

    #             if not out_iface:
    #                 self.logger.warning("No host-facing interface on %s for host %s (%s)",
    #                                     curr_switch, host_name, dst_ip)
    #                 continue

    #             out_port = int(out_iface["name"].split("eth")[-1])
    #             src_mac = out_iface["mac"]
    #             dst_mac = dst_host_mac
    #         else:
    #             # Next hop is another switch
    #             out_iface = next((iface for iface in self.switches[curr_switch]["interfaces"]
    #                             if iface.get("neighbor") == next_hop), None)
    #             in_iface_next = next((iface for iface in self.switches[next_hop]["interfaces"]
    #                                 if iface.get("neighbor") == curr_switch), None)
    #             if not out_iface or not in_iface_next:
    #                 self.logger.warning("Missing inter-switch iface for %s -> %s", curr_switch, next_hop)
    #                 continue
    #             out_port = int(out_iface["name"].split("eth")[-1])
    #             src_mac = out_iface["mac"]
    #             dst_mac = in_iface_next["mac"]


            # Determine output port and MAC addresses
    #         if next_hop in self.hosts:
    #             # Last hop to host
    #             dst_host_mac = self.hosts[dst_ip]["mac"]
    #             out_iface = next((iface for iface in self.switches[curr_switch]["interfaces"]
    #                             if ipaddress.ip_address(dst_ip) in ipaddress.ip_network(iface["subnet"])), None)
    #             if not out_iface: 
    #                 continue
    #             out_port = int(out_iface["name"].split("eth")[-1])
    #             src_mac = out_iface["mac"]
    #             dst_mac = dst_host_mac
    #         else:
    #             # Next hop is a switch
    #             out_iface = next((iface for iface in self.switches[curr_switch]["interfaces"]
    #                             if iface.get("neighbor") == next_hop), None)
    #             in_iface_next = next((iface for iface in self.switches[next_hop]["interfaces"]
    #                                 if iface.get("neighbor") == curr_switch), None)
    #             if not out_iface or not in_iface_next: 
    #                 continue
    #             out_port = int(out_iface["name"].split("eth")[-1])
    #             src_mac = out_iface["mac"]
    #             dst_mac = in_iface_next["mac"]

    #         # Create match and actions
    #         match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=dst_ip)
    #         actions = [
    #             parser.OFPActionSetField(eth_src=src_mac),
    #             parser.OFPActionSetField(eth_dst=dst_mac),
    #             parser.OFPActionDecNwTtl(),
    #             parser.OFPActionOutput(out_port)
    #         ]

    #         # Install the flow
    #         self.add_flow(dp, 10, match, actions)
    #         self.logger.info("Installed L3 flow on %s for dst %s -> port %d (MACs %s -> %s)",
    #                         curr_switch, dst_ip, out_port, src_mac, dst_mac)




    # # def install_path(self, path, dst_ip):
    # #     # Find the destination host's information from the config
    # #     dst_host_mac = self.hosts.get(dst_ip, {}).get("mac")
    # #     if not dst_host_mac:
    # #         self.logger.error("Destination host %s not in config", dst_ip)
    # #         return

    # #     # Install flows for each hop in the path
    # #     for i in range(len(path)):
    # #         s_name = path[i]
    # #         sw = self.switches[s_name]
    # #         dp = next((d for d in self.datapaths.values() if d.id == sw["dpid"]), None)
    # #         if not dp:
    # #             continue

    # #         parser = dp.ofproto_parser
            
    # #         # Determine the next hop and find the correct MACs and output port
    # #         if i < len(path) - 1:
    # #             # This is an intermediate switch-to-switch hop
    # #             next_s_name = path[i+1]
                
    # #             # Find the interface on the current switch facing the next switch
    # #             out_iface = next((iface for iface in sw["interfaces"] if iface.get("neighbor") == next_s_name), None)
    # #             if not out_iface: continue
                
    # #             # Find the interface on the next switch that connects back to the current one
    # #             next_sw_config = self.switches[next_s_name]
    # #             in_iface_next_hop = next((iface for iface in next_sw_config["interfaces"] if iface.get("neighbor") == s_name), None)
    # #             if not in_iface_next_hop: continue
                
    # #             out_port = int(out_iface["name"].split("eth")[-1])
    # #             new_src_mac = out_iface["mac"]
    # #             new_dst_mac = in_iface_next_hop["mac"]

    # #         else:
    # #             # This is the final hop from the last switch to the destination host
                
    # #             # Find the interface on the last switch connected to the destination host's subnet
    # #             dst_host_ip_obj = ipaddress.ip_address(dst_ip)
    # #             out_iface = next((iface for iface in sw["interfaces"] if dst_host_ip_obj in ipaddress.ip_network(iface["subnet"])), None)
    # #             if not out_iface: continue
                
    # #             out_port = int(out_iface["name"].split("eth")[-1])
    # #             new_src_mac = out_iface["mac"]
    # #             new_dst_mac = dst_host_mac # The final destination MAC is the host's MAC
            
    # #         # Define the match and actions for the flow rule
    # #         match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=dst_ip)
    # #         actions = [
    # #             parser.OFPActionSetField(eth_src=new_src_mac),
    # #             parser.OFPActionSetField(eth_dst=new_dst_mac),
    # #             parser.OFPActionDecNwTtl(),
    # #             parser.OFPActionOutput(out_port)
    # #         ]
    # #         self.add_flow(dp, 10, match, actions)
    # #         self.logger.info("Installed L3 flow on %s for dst %s -> port %d (MACs %s -> %s)", 
    # #                          s_name, dst_ip, out_port, new_src_mac, new_dst_mac)




    # # def install_path(self, path, dst_ip):
    # #     for i in range(len(path) - 1):
    # #         s1, s2 = path[i], path[i + 1]
    # #         sw = self.switches[s1]
    # #         out_port = None
    # #         for iface in sw["interfaces"]:
    # #             if iface["neighbor"] == s2:
    # #                 out_port = int(iface["name"].split("eth")[-1])
    # #                 break
    # #         if not out_port:
    # #             continue
    # #         dp = next((d for d in self.datapaths.values() if d.id == sw["dpid"]), None)
    # #         if dp:
    # #             parser = dp.ofproto_parser
    # #             match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=dst_ip)
    # #             actions = [parser.OFPActionOutput(out_port)]
    # #             self.add_flow(dp, 10, match, actions)
    # #             self.logger.info("Installed flow on %s for dst %s -> port %s", s1, dst_ip, out_port)

