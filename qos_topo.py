from mininet.topo import Topo

class QoSTopo(Topo):
    "Simple Topology for QoS Priority Controller: 1 Switch, 3 Hosts."

    def build(self):
        # Add a single OpenFlow switch
        switch = self.addSwitch('s1')

        # Add 3 hosts
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')

        # Connect all hosts to the central switch
        self.addLink(h1, switch)
        self.addLink(h2, switch)
        self.addLink(h3, switch)

# This dictionary allows Mininet to find your custom topology
topos = { 'qostopo': (lambda: QoSTopo()) }