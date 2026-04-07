from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types

class QoSPriorityController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(QoSPriorityController, self).__init__(*args, **kwargs)
        self.mac_to_port = {} # Dictionary to store MAC addresses and their ports

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """This runs when the switch first connects to the controller."""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Install a default "Table-miss" flow entry. 
        # If the switch doesn't know what to do with a packet, send it to the controller.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions):
        """Helper function to install a flow rule into the switch."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """This runs EVERY time the switch sends an unknown packet to the controller."""
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # Ignore IPv6 discovery packets
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        # 1. LEARN the source MAC address to avoid flooding next time
        self.mac_to_port[dpid][src] = in_port

        # 2. DECIDE where to send it
        if dst in self.mac_to_port[dpid]:
            # If we know where the destination is, send it to that specific port
            out_port = self.mac_to_port[dpid][dst]
        else:
            # If we don't know, flood it to all ports (broadcast)
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # 3. INSTALL a flow rule so the switch doesn't ask us about this pair again
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            # Standard priority rule
            self.add_flow(datapath, 1, match, actions)

        # 4. SEND the current packet out
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPActionOutput(out_port)
        packet_out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                         in_port=in_port, actions=[out], data=data)
        datapath.send_msg(packet_out)