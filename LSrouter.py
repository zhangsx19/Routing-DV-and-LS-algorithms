####################################################
# LSrouter.py
# Names:
# NetIds:
#####################################################

import sys
from collections import defaultdict
from router import Router
from packet import Packet
from json import dumps, loads
from LSP import LSP
from Queue import PriorityQueue

COST_MAX = 16
class LSrouter(Router):
    """Link state routing protocol implementation."""

    def __init__(self, addr, heartbeatTime):
        """class fields and initialization code here"""
        Router.__init__(self, addr)  # initialize superclass - don't remove
        self.routersLSP = {}  ### 
        self.routersAddr = {} ###
        self.routersPort = {} ### 
        self.routersNext = {} ### 
        self.routersCost = {} ### 
        self.seqnum = 0 ###  
        self.routersLSP[self.addr] = LSP(self.addr, 0, {}) 

        self.lasttime = None
        self.heartbeat = heartbeatTime

    def handlePacket(self, port, packet):
        """process incoming packet"""
        # deal with traceroute packet
        if packet.isTraceroute():
            if packet.dstAddr in self.routersNext:
                next_nb = self.routersNext[packet.dstAddr]
                self.send(self.routersPort[next_nb], packet)
        # deal with routing packet
        transfer = False
        if packet.isRouting():
            if packet.dstAddr == packet.srcAddr:
                return

            packetIn = loads(packet.content)
            addr = packetIn["addr"]
            seqnum = packetIn["seqnum"]
            nbcost = packetIn["nbcost"]
            if addr not in self.routersLSP:
                self.routersLSP[addr] = LSP(addr, seqnum, nbcost)
                transfer = True
            if self.routersLSP[addr].updateLSP(packetIn):
                transfer = True

            if transfer:
                for portNext in self.routersAddr:
                    if portNext != port:
                        packet.srcAddr = self.addr
                        packet.dstAddr = self.routersAddr[portNext]
                        self.send(portNext, packet)


    def handleNewLink(self, port, endpoint, cost):
        """handle new link"""
        self.routersAddr[port] = endpoint
        self.routersPort[endpoint] = port
        self.routersLSP[self.addr].nbcost[endpoint] = cost

        content = {}
        content["addr"] = self.addr
        content["seqnum"] = self.seqnum   
        content["nbcost"] = self.routersLSP[self.addr].nbcost
        self.seqnum += 1 # update the sequence number
        for port in self.routersAddr:
            packet = Packet(Packet.ROUTING, self.addr, self.routersAddr[port], dumps(content))
            self.send(port, packet)

    
    def calPath(self):
        # Dijkstra Algorithm for LS routing
        self.setCostMax()
        # put LSP info into a queue for operatisons
        Q = PriorityQueue()
        ListN = [self.addr]
        for addr, nbcost in self.routersLSP[self.addr].nbcost.items():
	        Q.put((nbcost, addr, addr)) 
        while not Q.empty():
            Cost, Addr, Next = Q.get(False)
            """TODO: write your codes here to build the routing table"""
            if Addr not in self.routersCost or self.routersCost[Addr] >= Cost:
                self.routersCost[Addr] = Cost
                self.routersNext[Addr] = Next
                ListN = ListN + [Addr]
                if Addr in self.routersLSP:
                    for addr, nbcost in self.routersLSP[Addr].nbcost.items():
                        if addr not in ListN:
                            Q.put((nbcost + Cost, addr, Next)) 

    def setCostMax(self):
        # intializtion for routing table 
        for addr in self.routersCost:
            self.routersCost[addr] = COST_MAX
        self.routersCost[self.addr] = 0
        self.routersNext[self.addr] = self.addr


    def handleRemoveLink(self, port):
        """handle removed link"""
        addr = self.routersAddr[port]
        self.routersLSP[self.addr].nbcost[addr] = COST_MAX
        self.calPath()

        content = {}
        content["addr"] = self.addr
        content["seqnum"] = self.seqnum + 1 
        content["nbcost"] = self.routersLSP[self.addr].nbcost
        self.seqnum += 1
        for port1 in self.routersAddr:
            if port1 != port:
                packet = Packet(Packet.ROUTING, self.addr, self.routersAddr[port1], dumps(content))
                self.send(port1, packet)
        pass

    def handleTime(self, timeMillisecs):
        """handle current time"""
        if (self.lasttime == None) or (timeMillisecs - self.lasttime > self.heartbeat):
            self.lasttime = timeMillisecs
            self.calPath()
      

    def debugString(self):
        """TODO: generate a string for debugging in network visualizer"""
        out = str(self.routersNext) + "\n" + str(self.routersCost) + "\n" + str(self.routersLSP)
        return out
