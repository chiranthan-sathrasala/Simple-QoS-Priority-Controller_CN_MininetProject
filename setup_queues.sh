#!/bin/bash
# This script creates QoS queues on the Mininet switch (s1)

echo "Clearing any existing QoS rules on s1..."
sudo ovs-vsctl --all destroy QoS
sudo ovs-vsctl --all destroy Queue

echo "Creating Queue 0 (Normal) and Queue 1 (VIP) on all switch ports..."

# We loop through all 3 ports on the switch (s1-eth1, s1-eth2, s1-eth3)
for port in s1-eth1 s1-eth2 s1-eth3; do
    sudo ovs-vsctl -- set Port $port qos=@newqos \
      -- --id=@newqos create QoS type=linux-htb other-config:max-rate=100000000 queues=0=@q0,1=@q1 \
      -- --id=@q0 create Queue other-config:max-rate=20000000 \
      -- --id=@q1 create Queue other-config:min-rate=80000000
done

echo "QoS Queues successfully created on switch s1!"