from base import BaseController

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types


class HubController(BaseController):
    """Hub Controller: Floods all packets (acts like a hub)"""

    def __init__(self, *args, **kwargs):
        super(HubController, self).__init__(*args, **kwargs)

    # when packet arrives
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            # Ignore LLDP packets used for topology discovery
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        # Initialize table for this switch if not exists
        self.mac_to_port.setdefault(dpid, {})

        # controller learns the source MAC → port mapping
        self.mac_to_port[dpid][src] = in_port

        # If destination known, forward to that port; else flood
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
            self.logger.info("Hub: Forwarding %s -> %s via port %s on switch %s",
                             src, dst, out_port, dpid)
        else:
            out_port = ofproto.OFPP_FLOOD
            self.logger.info("Hub: Flooding %s -> %s on switch %s",
                             src, dst, dpid)

        actions = [parser.OFPActionOutput(out_port)]

        # Send packet out (always via controller, no flow mods)
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        datapath.send_msg(out)