# p4_l3spf_lf.py
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, arp, ether_types, icmp
from ryu.topology import event
import networkx as nx
import ipaddress
import json
import logging

class L3ShortestPathLinkFailure(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(L3ShortestPathLinkFailure, self).__init__(*args, **kwargs)
        self.logger.setLevel(logging.INFO)

        with open("./part4/p4_config.json") as f:
            self.cfg = json.load(f)

        self.graph = nx.Graph()
        for link in self.cfg["links"]:
            self.graph.add_edge(link["src"], link["dst"], weight=link["cost"])

        self.switches = {s["name"]: s for s in self.cfg["switches"]}
        self.hosts = {h["ip"]: h for h in self.cfg["hosts"]}
        self.datapaths = {}
        self.logger.info("Loaded config and built initial graph.")

    # --- NEW: Link Failure Handling ---
    def _clear_all_flows(self):
        """Clears all L3 flows (priority 10) from all connected switches."""
        self.logger.info("Clearing all L3 flow rules from all switches...")
        for dp in self.datapaths.values():
            parser = dp.ofproto_parser
            ofproto = dp.ofproto
            # Match only our L3 flows (priority 10)
            match = parser.OFPMatch()
            mod = parser.OFPFlowMod(datapath=dp,
                                    command=ofproto.OFPFC_DELETE,
                                    out_port=ofproto.OFPP_ANY,
                                    out_group=ofproto.OFPG_ANY,
                                    priority=10,
                                    match=match)
            dp.send_msg(mod)

    @set_ev_cls(event.EventLinkDelete)
    def link_down_handler(self, ev):
        link = ev.link
        src_dpid = link.src.dpid
        dst_dpid = link.dst.dpid
        
        # Find switch names from DPIDs
        src_name = next((s['name'] for s in self.switches.values() if s['dpid'] == src_dpid), None)
        dst_name = next((s['name'] for s in self.switches.values() if s['dpid'] == dst_dpid), None)

        if src_name and dst_name and self.graph.has_edge(src_name, dst_name):
            self.graph.remove_edge(src_name, dst_name)
            self.logger.warning(f"Link DOWN: {src_name} <-> {dst_name}. Removed edge from graph.")
            self._clear_all_flows()

    @set_ev_cls(event.EventLinkAdd)
    def link_up_handler(self, ev):
        link = ev.link
        src_dpid = link.src.dpid
        dst_dpid = link.dst.dpid

        src_name = next((s['name'] for s in self.switches.values() if s['dpid'] == src_dpid), None)
        dst_name = next((s['name'] for s in self.switches.values() if s['dpid'] == dst_dpid), None)

        if src_name and dst_name and not self.graph.has_edge(src_name, dst_name):
            # Find original cost from config
            cost = next((l['cost'] for l in self.cfg['links'] if (l['src'] == src_name and l['dst'] == dst_name) or (l['src'] == dst_name and l['dst'] == src_name)), 1)
            self.graph.add_edge(src_name, dst_name, weight=cost)
            self.logger.info(f"Link UP: {src_name} <-> {dst_name}. Added edge back to graph.")
            # Clearing flows on link up can also help force re-convergence
            self._clear_all_flows()

    # --- Existing Helper Functions (no changes needed) ---
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
        icmp_pkt = pkt.get_protocol(icmp.icmp)
        if not icmp_pkt or icmp_pkt.type != icmp.ICMP_ECHO_REQUEST: return False
        my_ip = ip_pkt.dst
        my_mac = None
        s_name = self.find_router_for_ip(my_ip)
        if not s_name: return False
        switch_config = self.switches.get(s_name)
        for iface in switch_config.get("interfaces", []):
            if iface.get("ip") == my_ip:
                my_mac = iface.get("mac"); break
        if not my_mac: return False
        p = packet.Packet()
        p.add_protocol(ethernet.ethernet(ethertype=eth.ethertype, dst=eth.src, src=my_mac))
        p.add_protocol(ipv4.ipv4(dst=ip_pkt.src, src=my_ip, proto=ip_pkt.proto))
        p.add_protocol(icmp.icmp(type_=icmp.ICMP_ECHO_REPLY, code=icmp.ICMP_ECHO_REPLY_CODE, csum=0, data=icmp_pkt.data))
        p.serialize()
        actions = [dp.ofproto_parser.OFPActionOutput(port=in_port)]
        out = dp.ofproto_parser.OFPPacketOut(datapath=dp, buffer_id=dp.ofproto.OFP_NO_BUFFER, in_port=dp.ofproto.OFPP_CONTROLLER, actions=actions, data=p.data)
        dp.send_msg(out)
        self.logger.info("Sent ICMP Echo Reply for %s from %s", my_ip, s_name)
        return True

    # --- Event Handlers (no changes needed) ---
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        match = dp.ofproto_parser.OFPMatch()
        actions = [dp.ofproto_parser.OFPActionOutput(dp.ofproto.OFPP_CONTROLLER, dp.ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)
        self.logger.info("Switch %s connected", dp.id)
    
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP: return
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt:
            self.handle_arp(dp, in_port, eth, arp_pkt)
            return
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            self.handle_ipv4(dp, in_port, pkt, eth, ip_pkt)

    def handle_arp(self, dp, in_port, eth, arp_pkt):
        if arp_pkt.opcode != arp.ARP_REQUEST: return
        dst_ip = arp_pkt.dst_ip
        for s in self.switches.values():
            for i in s["interfaces"]:
                if i["ip"] == dst_ip:
                    e = ethernet.ethernet(dst=eth.src, src=i["mac"], ethertype=ether_types.ETH_TYPE_ARP)
                    a = arp.arp(hwtype=1, proto=0x0800, hlen=6, plen=4, opcode=arp.ARP_REPLY, src_mac=i["mac"], src_ip=dst_ip, dst_mac=eth.src, dst_ip=arp_pkt.src_ip)
                    p = packet.Packet()
                    p.add_protocol(e); p.add_protocol(a)
                    p.serialize()
                    actions = [dp.ofproto_parser.OFPActionOutput(in_port)]
                    out = dp.ofproto_parser.OFPPacketOut(datapath=dp, buffer_id=dp.ofproto.OFP_NO_BUFFER, in_port=dp.ofproto.OFPP_CONTROLLER, actions=actions, data=p.data)
                    dp.send_msg(out)
                    self.logger.info("Replied to ARP for %s", dst_ip)
                    return

    def handle_ipv4(self, dp, in_port, pkt, eth, ip_pkt):
        if self._handle_icmp_request(dp, pkt, eth, ip_pkt, in_port): return
        src_ip, dst_ip = ip_pkt.src, ip_pkt.dst
        src_router = self.find_router_for_ip(src_ip)
        dst_router = self.find_router_for_ip(dst_ip)
        if not src_router or not dst_router:
            self.logger.warning("Unknown subnet for %s -> %s", src_ip, dst_ip)
            return
        try:
            path = nx.shortest_path(self.graph, src_router, dst_router, weight="weight")
            self.logger.info("Path %s -> %s : %s", src_ip, dst_ip, path)
            self.install_path(path, dst_ip)
            self.install_path(list(reversed(path)), src_ip)
        except nx.NetworkXNoPath:
            self.logger.error("No path from %s to %s in current graph.", src_router, dst_router)

    def install_path(self, path, dst_ip):
        for i in range(len(path)):
            s_name = path[i]
            dp = next((d for d in self.datapaths.values() if d.id == self.switches[s_name]["dpid"]), None)
            if not dp: continue
            parser, ofproto = dp.ofproto_parser, dp.ofproto
            
            # Final hop to host
            if i == len(path) - 1:
                host = self.hosts.get(dst_ip)
                if not host: continue
                out_iface = next((iface for iface in self.switches[s_name]["interfaces"] if iface.get("neighbor") == host['name']), None)
                if not out_iface: continue
                out_port = int(out_iface["name"].split("eth")[-1])
                src_mac, dst_mac = out_iface["mac"], host["mac"]
            # Switch-to-switch hop
            else:
                next_s_name = path[i+1]
                out_iface = next((iface for iface in self.switches[s_name]["interfaces"] if iface.get("neighbor") == next_s_name), None)
                in_iface_next = next((iface for iface in self.switches[next_s_name]["interfaces"] if iface.get("neighbor") == s_name), None)
                if not out_iface or not in_iface_next: continue
                out_port = int(out_iface["name"].split("eth")[-1])
                src_mac, dst_mac = out_iface["mac"], in_iface_next["mac"]
            
            match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP, ipv4_dst=dst_ip)
            actions = [
                parser.OFPActionSetField(eth_src=src_mac),
                parser.OFPActionSetField(eth_dst=dst_mac),
                parser.OFPActionDecNwTtl(),
                parser.OFPActionOutput(out_port)
            ]
            self.add_flow(dp, 10, match, actions)
            self.logger.info("Installed L3 flow on %s for dst %s -> port %d", s_name, dst_ip, out_port)