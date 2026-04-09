from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib.packet import ipv4
from ryu.lib.packet import in_proto

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
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]
        queue_id = 0 # Default to normal queue
        flow_priority = 1 # Default flow rule priority

        # --- QOS LOGIC START ---
        # Check if the packet is an IPv4 packet
        if eth.ethertype == ether_types.ETH_TYPE_IP:
            ip = pkt.get_protocol(ipv4.ipv4)
            
            # Identify ICMP (Ping) Traffic [VIP Lame]
            if ip.proto == in_proto.IPPROTO_ICMP:
                queue_id = 1  # Assign to high-priority queue
                flow_priority = 10 # Higher rule priority so it matches first
                
                # Add the queue action BEFORE the output action
                actions = [parser.OFPActionSetQueue(queue_id), parser.OFPActionOutput(out_port)]
                
                if out_port != ofproto.OFPP_FLOOD:
                    match = parser.OFPMatch(in_port=in_port, eth_type=ether_types.ETH_TYPE_IP, 
                                            ip_proto=in_proto.IPPROTO_ICMP, eth_dst=dst, eth_src=src)
                    self.add_flow(datapath, flow_priority, match, actions)
                    print(f"VIP Ping Flow installed: h{src} -> h{dst} via Queue {queue_id}")

            # Identify TCP Traffic [Normal Lane]
            elif ip.proto == in_proto.IPPROTO_TCP:
                queue_id = 0  # Assign to normal queue
                flow_priority = 5
                
                actions = [parser.OFPActionSetQueue(queue_id), parser.OFPActionOutput(out_port)]
                
                if out_port != ofproto.OFPP_FLOOD:
                    match = parser.OFPMatch(in_port=in_port, eth_type=ether_types.ETH_TYPE_IP, 
                                            ip_proto=in_proto.IPPROTO_TCP, eth_dst=dst, eth_src=src)
                    self.add_flow(datapath, flow_priority, match, actions)
                    print(f"Standard TCP Flow installed: h{src} -> h{dst} via Queue {queue_id}")
        
        # Fallback for all other non-IP traffic (like ARP)
        elif out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(datapath, 1, match, actions)
        # --- QOS LOGIC END ---

        # 4. SEND the current packet out
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        
        # We must use the specific actions list we built above (which includes the queue)
        packet_out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                         in_port=in_port, actions=actions, data=data)
        datapath.send_msg(packet_out)