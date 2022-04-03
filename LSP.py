class LSP(object):

    def __init__(self, addr, seqnum, nbcost):
        self.addr = addr
        self.seqnum = seqnum
        self.nbcost = nbcost

    def updateLSP(self, packetIn):
        if self.seqnum >= packetIn["seqnum"]:
            return False
        self.seqnum = packetIn["seqnum"]
        if self.nbcost == packetIn["nbcost"]:
            return False
        if self.nbcost != packetIn["nbcost"]:
            self.nbcost = packetIn["nbcost"]
            return True


