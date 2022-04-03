####################################################
# DVrouter.py
# Names:
# NetIds:
#####################################################

import sys
from collections import defaultdict
from router import Router
from packet import Packet
from json import dumps, loads

COST_MAX = 16
class DVrouter(Router):
    """Distance vector routing protocol implementation."""

    def __init__(self, addr, heartbeatTime):
        """class fields and initialization code here"""
        Router.__init__(self, addr)  # initialize superclass - don't remove
        self.routersNext = {}  
        self.routersCost = {} 
        self.routersPort = {} 
        self.routersAddr = {}  
        self.heartbeat = heartbeatTime
        self.lasttime = None

    def handlePacket(self, port, packet):
        """process incoming packet"""
        # deal with traceroute packet
        if packet.isTraceroute():
            if packet.dstAddr in self.routersNext:
                next_nb = self.routersNext[packet.dstAddr]
                self.send(self.routersPort[next_nb], packet)

        # deal with routing packet
        if packet.isRouting():
            rtn = self.updateNode(packet.content)
            # if rtn=None, irrelevant Routing Information
            if rtn != None:
                # routing table updated, need to be broadcast
                for port in self.routersAddr:  # this port is diff from input port
                    content = {}
                    content["src"] = self.addr
                    content["dst"] = rtn[1]  # packet dst
                    content["cost"] = rtn[2] # cost
                    if self.routersAddr[port] != self.routersNext[rtn[1]]:   # split horizon 
                        content_str = dumps(content)
                        # send the update route tb to neighbour node (ending point of port)
                        packet = Packet(Packet.ROUTING, self.addr, self.routersAddr[port], content_str)
                        self.send(port, packet)

    def updateNode(self, content):
        """update node with routing packet"""
        data = loads(content)
        src = data["src"]
        dst = data["dst"]
        cost = data["cost"]
        # build the src-dst link
        if dst not in self.routersCost and dst != self.addr:
            if src in self.routersCost:
                self.routersCost[dst] = self.routersCost[src] + cost
                self.routersNext[dst] = src
                return True, dst, self.routersCost[dst]

        # choose the less cost or new info
        if dst in self.routersCost:
            if src in self.routersCost:
                if (self.routersCost[dst] > self.routersCost[src] + cost) or (self.routersNext[dst] == src and src != dst):
                    self.routersCost[dst] = self.routersCost[src] + cost
                    self.routersNext[dst] = src
                    # set COST_MAX as infinity
                    if self.routersCost[dst] >  COST_MAX:
                        self.routersCost[dst] =  COST_MAX
                    return True, dst, self.routersCost[dst]

        return None


    def handleNewLink(self, port, endpoint, cost):
        """handle new link"""
        for router in self.routersPort:
            # endpoint maybe connect to router via other nodes, now the new link connects them directly.
            if (endpoint not in self.routersCost) or (self.routersCost[endpoint] > cost):
                content = {}
                content["src"] = self.addr
                content["dst"] = endpoint
                content["cost"] = cost
                content_str = dumps(content)
                packet = Packet(Packet.ROUTING, self.addr, router, content_str)
                # send the new router info to other routers
                self.send(self.routersPort[router], packet)

                content1 = {}
                content1["src"] = self.addr
                content1["dst"] = router
                content1["cost"] = self.routersCost[router]
                content1_str = dumps(content1)
                packet1 = Packet(Packet.ROUTING, self.addr,
                                 endpoint, content1_str)
                # send other router infos to the new router
                self.send(port, packet1)
        # update the routing table at self
        self.routersPort[endpoint] = port
        self.routersAddr[port] = endpoint
        if (endpoint not in self.routersCost) or (self.routersCost[endpoint] > cost):
            self.routersCost[endpoint] = cost
            self.routersNext[endpoint] = endpoint


    def handleRemoveLink(self, port):
        """handle removed link"""
        addr = self.routersAddr[port]
        self.routersCost[addr] =  COST_MAX
        for addr1 in self.routersNext:
            if self.routersNext[addr1] == addr:
                self.routersCost[addr1] =  COST_MAX
        if addr == self.addr:
            self.routersCost[addr] = 0
            self.routersNext[addr] = addr


    def handleTime(self, timeMillisecs):
        """handle current time"""
        if (self.lasttime == None) or (timeMillisecs - self.lasttime > self.heartbeat):
            self.lasttime = timeMillisecs

            for addr1 in self.routersPort:
                for dst1 in self.routersCost:
                    content1 = {}
                    content1["src"] = self.addr
                    content1["dst"] = dst1
                    content1["cost"] = self.routersCost[dst1]
                    content1_str = dumps(content1)
                    packet1 = Packet(Packet.ROUTING, self.addr,
                                     addr1, content1_str)
                    # send DV to neighbor nodes
                    self.send(self.routersPort[addr1], packet1)


    def debugString(self):
        """generate a string for debugging in network visualizer"""
        out = str(self.routersNext) + "\n" + str(self.routersCost) + "\n" 
        return out

