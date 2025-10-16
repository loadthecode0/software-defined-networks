# base_sp_controller.py  (replace your BaseSPController with this)
import json
import logging
from collections import defaultdict
from typing import List

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub
from ryu.lib.packet import lldp as ryu_lldp

LLDP_ETH_TYPE = 0x88cc

from graph_utils import NetworkGraph


class BaseSPController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(BaseSPController, self).__init__(*args, **kwargs)
        self.logger.setLevel(logging.INFO)

        # config + graph
        self.config_path = "./part2/config.json"
        self.graph = NetworkGraph(self.config_path)

        # state
        self.datapaths = {}                # dpid -> datapath
        self.mac_to_port = defaultdict(dict)  # dpid -> {mac:port}
        self.host_location = {}           # mac -> (dpid,port)
        self.adjacency = defaultdict(dict)  # dpid -> {neighbor_dpid: out_port}

        # LLDP thread (runs continuously; will skip until datapaths are present)
        self.lldp_interval = 2.0  # seconds
        self.lldp_thread = hub.spawn(self._lldp_loop)

    # ------------------ OF helpers ------------------
    def add_flow(self, datapath, priority, match, actions,
                 buffer_id=None, idle_timeout=0, hard_timeout=0):
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
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=buffer_id,
                                  in_port=in_port,
                                  actions=actions,
                                  data=data if buffer_id == ofproto.OFP_NO_BUFFER else None)
        datapath.send_msg(out)

    # ------------------ Switch connect ------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        dpid = dp.id
        self.logger.info("Switch %s connected", dpid)
        self.datapaths[dpid] = dp

        # install table-miss
        parser = dp.ofproto_parser
        ofproto = dp.ofproto
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)

        # request port desc right away (this triggers port_desc_handler)
        req = parser.OFPPortDescStatsRequest(dp, 0)
        dp.send_msg(req)

    # ------------------ LLDP sending / receiving ------------------
    def _lldp_loop(self):
        """Periodically request port desc and send LLDP (works even if started early)."""
        while True:
            if not self.datapaths:
                hub.sleep(self.lldp_interval)
                continue
            # send port description request for every datapath (port_desc_handler will send LLDP)
            for dp in list(self.datapaths.values()):
                try:
                    parser = dp.ofproto_parser
                    req = parser.OFPPortDescStatsRequest(dp, 0)
                    dp.send_msg(req)
                except Exception as e:
                    self.logger.exception("Failed sending portdesc req to dpid=%s: %s", dp.id, e)
            hub.sleep(self.lldp_interval)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_handler(self, ev):
        """When switch reports ports, send LLDP Packets out each port so neighbors will generate PacketIn."""
        dp = ev.msg.datapath
        dpid = dp.id
        parser = dp.ofproto_parser
        ofproto = dp.ofproto

        self.logger.debug("PortDesc reply from s%s: %s ports", dpid, len(ev.msg.body))

        for p in ev.msg.body:
            # skip the LOCAL port
            if p.port_no >= ofproto.OFPP_MAX or p.port_no == ofproto.OFPP_LOCAL:
                continue

            # Build LLDP packet carrying (dpid, port_no)
            lldp_pkt = self._build_lldp(dpid, p.port_no)
            lldp_pkt.serialize()
            data = lldp_pkt.data
            actions = [parser.OFPActionOutput(p.port_no)]
            out = parser.OFPPacketOut(datapath=dp,
                                      buffer_id=ofproto.OFP_NO_BUFFER,
                                      in_port=ofproto.OFPP_CONTROLLER,
                                      actions=actions,
                                      data=data)
            dp.send_msg(out)
            self.logger.debug("Sent LLDP from s%s port %s", dpid, p.port_no)

    def _build_lldp(self, dpid, port_no):
        """Return a Packet() containing LLDP TLVs with chassis=dpid, port=port_no"""
        chassis = ryu_lldp.ChassisID(
            subtype=ryu_lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
            chassis_id=str(dpid).encode("utf-8"))
        portid = ryu_lldp.PortID(
            subtype=ryu_lldp.PortID.SUB_PORT_COMPONENT,
            port_id=str(port_no).encode("utf-8"))
        ttl = ryu_lldp.TTL(ttl=10)
        tlvs = (chassis, portid, ttl, ryu_lldp.End())

        ether = ethernet.ethernet(dst=ryu_lldp.LLDP_MAC_NEAREST_BRIDGE,
                                  src="00:00:00:00:00:01",
                                  ethertype=LLDP_ETH_TYPE)
        pkt = packet.Packet()
        pkt.add_protocol(ether)
        pkt.add_protocol(ryu_lldp.lldp(tlvs))
        return pkt

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def lldp_handler(self, ev):
        """Handle LLDP PacketIns and populate adjacency."""
        msg = ev.msg
        dp = msg.datapath
        dpid = dp.id
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return

        # Only handle LLDP here; leave other PacketIns to subclass handlers
        if eth.ethertype != LLDP_ETH_TYPE:
            return

        lldp_pkt = pkt.get_protocol(ryu_lldp.lldp)
        if not lldp_pkt or not hasattr(lldp_pkt, 'tlvs'):
            return

        # Extract chassis and port from TLVs (we encoded them as bytes of ascii dpid/port)
        try:
            chassis_tlv = lldp_pkt.tlvs[0]
            port_tlv = lldp_pkt.tlvs[1]
            src_dpid = int(chassis_tlv.chassis_id.decode("utf-8"))
            src_port = int(port_tlv.port_id.decode("utf-8"))
        except Exception as e:
            self.logger.exception("Failed to parse LLDP TLV: %s", e)
            return

        dst_dpid = dpid
        dst_port = msg.match.get('in_port')  # port where LLDP arrived

        # populate adjacency both ways
        # out port on src_dpid to reach dst_dpid is src_port (when sending)
        # but the local port on dst_dpid which observed it is dst_port
        self.adjacency[src_dpid][dst_dpid] = src_port
        self.adjacency[dst_dpid][src_dpid] = dst_port
        # self.logger.info("Discovered link: s%s:%s <-> s%s:%s", src_dpid, src_port, dst_dpid, dst_port)
        # self.logger.info("Adjacency now: %s", dict(self.adjacency))

    # ------------------ Subclass hooks ------------------
    def choose_path(self, all_paths: List[List[str]]) -> List[str]:
        return all_paths[0] if all_paths else []

    def install_path_flows(self, path: List[str], src_mac=None, dst_mac=None):
        self.logger.info("Installing flows along path %s", path)
