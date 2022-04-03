import sys
import tkFont
import json
import thread
import time
import threading
import pickle
import signal
import os.path
import Queue
from Tkinter import *
from collections import defaultdict
from client import Client
from router import Router
from packet import Packet
from link import Link
from DVrouter import DVrouter
from LSrouter import LSrouter

# DVRouter and LSRouter imports placed in main and conditioned by DV|LS

class Network:
    """Network class maintains all clients, routers, links, and confguration"""

    def __init__(self, netJsonFilepath, routerClass, visualize=False):
        """Create a new network from the parameters in the file at
           netJsonFilepath.  routerClass determines whether to use DVrouter,
           LSrouter, or the default Router"""

        # parse configuration details
        netJsonFile = open(netJsonFilepath, 'r')
        netJson = json.load(netJsonFile)
        self.latencyMultiplier = 100
        self.endTime = netJson["endTime"] * self.latencyMultiplier
        self.visualize = visualize
        if visualize:
            self.latencyMultiplier *= netJson["visualize"]["timeMultiplier"]
        self.clientSendRate = netJson["clientSendRate"]*self.latencyMultiplier

        # parse and create routers, clients, and links
        self.routers = self.parseRouters(netJson["routers"], routerClass)
        self.clients = self.parseClients(netJson["clients"], self.clientSendRate)
        self.links = self.parseLinks(netJson["links"])

        # parse link changes
        if "changes" in netJson:
            self.changes = self.parseChanges(netJson["changes"])
        else:
            self.changes = None

        # parse correct routes and create some tracking fields
        self.correctRoutes = self.parseCorrectRoutes(netJson["correctRoutes"])
        self.threads = []
        self.routes = {}
        self.routesLock = threading.Lock()
        netJsonFile.close()


    def parseRouters(self, routerParams, routerClass):
        """Parse routes from routerParams dict"""
        routers = {}
        for addr in routerParams:
            #print "Router {}".format(addr)
            routers[addr] = routerClass(addr, heartbeatTime=self.latencyMultiplier*10)
        return routers


    def parseClients(self, clientParams, clientSendRate):
        """Parse clients from clientParams dict"""
        clients = {}
        for addr in clientParams:
            #print "Client {}".format(addr)
            clients[addr] = Client(addr, clientParams, clientSendRate, self.updateRoute)
        return clients


    def parseLinks(self, linkParams):
        """Parse links from linkParams, dict"""
        links = {}
        for addr1, addr2, p1, p2, c12, c21 in linkParams:
            #print "{}:{} --cost:{}--> {}:{} --cost:{}--> {}:{}".format(
                   #addr1, p1, c12, addr2, p2, c21, addr1, p1)
            link = Link(addr1, addr2, c12, c21, self.latencyMultiplier)
            links[(addr1,addr2)] = (p1, p2, c12, c21, link)
        return links


    def parseChanges(self, changesParams):
        """Parse link changes from changesParams dict"""
        changes = Queue.PriorityQueue()
        for change in changesParams:
            #print change
            changes.put(change)
        return changes


    def parseCorrectRoutes(self, routesParams):
        """parse correct routes, from routesParams dict"""
        correctRoutes = defaultdict(list)
        for route in routesParams:
            src, dst = route[0], route[-1]
            correctRoutes[(src,dst)].append(route)
        return correctRoutes


    def run(self):
        """Run the network.  Start threads for each client and router. Start
           thread to track link changes.  """
        for router in self.routers.values():
            thread = router_thread(router)
            thread.start()
            self.threads.append(thread)
        for client in self.clients.values():
            thread = client_thread(client)
            thread.start()
            self.threads.append(thread)
        self.addLinks()
        if self.changes:
            self.handleChangesThread = handle_changes_thread(self)
            self.handleChangesThread.start()
        if not self.visualize:
            signal.signal(signal.SIGINT, self.handleInterrupt)
            time.sleep(self.endTime/float(1000))
            self.finalRoutes()
            sys.stdout.write("\n"+self.getRouteString()+"\n")
            self.joinAll()



    def addLinks(self):
        """Add links to clients and routers"""
        for addr1, addr2 in self.links:
            p1, p2, c12, c21, link = self.links[(addr1, addr2)]
            if addr1 in self.clients:
                self.clients[addr1].changeLink(("add", link))
            if addr2 in self.clients:
                self.clients[addr2].changeLink(("add", link))
            if addr1 in self.routers:
                self.routers[addr1].changeLink(("add", p1, addr2, link, c12))
            if addr2 in self.routers:
                self.routers[addr2].changeLink(("add", p2, addr1, link, c21))


    def handleChanges(self):
        """Handle changes to links. Run this method in a separate thread.
           Uses a priority queue to track time of next change"""
        startTime = time.time()*1000
        while not self.changes.empty():
            changeTime, target, change = self.changes.get()
            currentTime = time.time()*1000
            waitTime = (changeTime*self.latencyMultiplier + startTime) - currentTime
            if waitTime > 0:
                time.sleep(waitTime/float(1000))
            # link changes
            if change == "up":
                addr1, addr2, p1, p2, c12, c21 = target
                link = Link(addr1, addr2, c12, c21, self.latencyMultiplier)
                self.links[(addr1,addr2)] = (p1, p2, c12, c21, link)
                self.routers[addr1].changeLink(("add", p1, addr2, link, c12))
                self.routers[addr2].changeLink(("add", p2, addr1, link, c21))
            elif change == "down":
                addr1, addr2, = target
                p1, p2, _, _, link = self.links[(addr1, addr2)]
                self.routers[addr1].changeLink(("remove", p1))
                self.routers[addr2].changeLink(("remove", p2))
            # update visualization
            if hasattr(Network, "visualizeChangesCallback"):
                Network.visualizeChangesCallback(change, target)


    def updateRoute(self, src, dst, route):
        """Callback function used by clients to update the
           current routes taken by traceroute packets"""
        self.routesLock.acquire()
        timeMillisecs = int(round(time.time() * 1000))
        isGood = route in self.correctRoutes[(src,dst)]  

        try:
            _, _, currentTime = self.routes[(src,dst)]
            if timeMillisecs > currentTime:
                self.routes[(src,dst)] = (route, isGood, timeMillisecs)
        except KeyError:
            self.routes[(src,dst)] = (route, isGood, timeMillisecs)
        finally:
            self.routesLock.release()


    def getRouteString(self, labelIncorrect=True):
        """Create a string with all the current routes found by traceroute
           packets and whether they are correct"""
        self.routesLock.acquire()
        routeStrings = []
        allCorrect = True
        for src,dst in self.routes:
            route, isGood, _ = self.routes[(src,dst)]
            routeStrings.append("{} -> {}: {} {}".format(src, dst, route,
                "" if (isGood or not labelIncorrect) else "Incorrect Route"))     # check if the routing is correct
            if not isGood:
                allCorrect = False
        routeStrings.sort()
        if allCorrect and len(self.routes) > 0:
            routeStrings.append("\nSUCCESS: All Routes correct!")
        else:
            routeStrings.append("\nFAILURE: Not all routes are correct")
        routeString = "\n".join(routeStrings)
        self.routesLock.release()
        return routeString


    def getRoutePickle(self):
        """Create a pickle with the current routes
           found by traceroute packets"""
        self.routesLock.acquire()
        routePickle = pickle.dumps(self.routes)
        self.routesLock.release()
        return routePickle


    def resetRoutes(self):
        """Reset the routes foudn by traceroute packets"""
        self.routesLock.acquire()
        self.routes = {}
        self.routesLock.release()


    def finalRoutes(self):
        """Have the clients send one final batch of traceroute packets"""
        self.resetRoutes()
        for client in self.clients.values():
            client.lastSend()
        time.sleep(4*self.clientSendRate/float(1000))

    def joinAll(self):
        if self.changes:
            self.handleChangesThread.join()
        for thread in self.threads:
            thread.join()

    def handleInterrupt(self, signum, _):
        self.joinAll()
        print ''
        quit()


# Extensions of threading.Thread class

class router_thread(threading.Thread):

    def __init__(self, router):
        threading.Thread.__init__(self)
        self.router = router

    def run(self):
        self.router.runRouter()

    def join(self, timeout=None):
        # Terrible style (think about changing) but works like a charm
        self.router.keepRunning = False
        super(router_thread, self).join(timeout)

class client_thread(threading.Thread):

    def __init__(self, client):
        threading.Thread.__init__(self)
        self.client = client

    def run(self):
        self.client.runClient()

    def join(self, timeout=None):
        # Terrible style (think about changing) but works like a charm
        self.client.keepRunning = False
        super(client_thread, self).join(timeout)

class handle_changes_thread(threading.Thread):

    def __init__(self, network):
        threading.Thread.__init__(self)
        self.network = network

    def run(self):
        self.network.handleChanges()

class App:
    """Tkinter GUI application for network simulation visualizations"""

    def __init__(self, root, network, networkParams):
        self.network = network
        self.networkParams = networkParams
        Packet.animate = self.packetSend
        Network.visualizeChangesCallback = self.visualizeChanges
        self.animateRate = networkParams["visualize"]["animateRate"]
        self.latencyCorrection = networkParams["visualize"]["latencyCorrection"]
        self.clientFollowing = None
        self.routerFollowing = None
        self.displayCurrentRoutesRate = 100
        self.displayCurrentDebugRate = 50

        # enclosing frame
        self.frame = Frame(root)
        self.frame.grid(padx=10, pady=10)

        # canvas for drawing network
        self.canvasWidth = networkParams["visualize"]["canvasWidth"]
        self.canvasHeight = networkParams["visualize"]["canvasHeight"]
        self.canvas = Canvas(self.frame, width=self.canvasWidth, height=self.canvasHeight)
        self.canvas.grid(column=1, row=1, rowspan=4)

        # text for displaying current routes
        self.routeLabel = Label(self.frame, text="Current routes:")
        self.routeLabel.grid(column=3, row=1)
        self.routeScrollbar = Scrollbar(self.frame)
        self.routeScrollbar.grid(column=2, row=2, sticky=NE+SE)
        self.routeText = Text(self.frame, yscrollcommand=self.routeScrollbar.set)
        self.routeText.grid(column=3, row=2)

        # text for displaying debugging information
        self.debugLabel = Label(self.frame, text="Click on routers to print debug string below:")
        self.debugLabel.grid(column=3, row=3)
        self.debugScrollbar = Scrollbar(self.frame)
        self.debugScrollbar.grid(column=2, row=4, sticky=NE+SE)
        self.debugText = Text(self.frame, yscrollcommand=self.debugScrollbar.set)
        self.debugText.grid(column=3, row=4)

        self.rectCenters = self.calcRectCenters()
        self.lines, self.lineLabels = self.drawLines()
        self.rects = self.drawRectangles()

        #self.drawNetwork()
        thread.start_new_thread(self.network.run, ())
        thread.start_new_thread(self.displayCurrentRoutes, ())
        thread.start_new_thread(self.displayCurrentDebug, ())

    def calcRectCenters(self):
        """Compute the centers of the rectangles representing clients/routers"""
        rectCenters = {}
        gridSize = int(self.networkParams["visualize"]["gridSize"])
        self.boxWidth = self.canvasWidth / gridSize
        self.boxHeight = self.canvasHeight / gridSize
        for label in self.networkParams["visualize"]["locations"]:
            gx,gy = self.networkParams["visualize"]["locations"][label]
            rectCenters[label] = (gx*self.boxWidth + self.boxWidth/2,
                                  gy*self.boxHeight + self.boxHeight/2)
        return rectCenters


    def drawLines(self):
        """draw lines corresponding to links"""
        lines = {}
        lineLabels = {}
        for addr1, addr2, p1, p2, c12, c21 in self.networkParams["links"]:
            line, lineLabel = self.drawLine(addr1, addr2, c12, c21)
            lines[(addr1, addr2)] = line
            lineLabels[(addr1, addr2)] = lineLabel
        return lines, lineLabels


    def drawLine(self, addr1, addr2, c12, c21):
        """draw a single line corresponding to one link"""
        center1, center2 = self.rectCenters[addr1], self.rectCenters[addr2]
        line = self.canvas.create_line(center1[0], center1[1], center2[0], center2[1],
                                       width=self.networkParams["visualize"]["lineWidth"], fill=self.networkParams["visualize"]["lineColor"])
        self.canvas.tag_lower(line)
        tx, ty = (center1[0] + center2[0])/2, (center1[1] + center2[1])/2
        t = str(c12) if c12 == c21 else "{}->{}:{}, {}->{}:{}".format(addr1, addr2, c12, addr2, addr1, c21)
        label = self.canvas.create_text(tx, ty, text=t,
                                       state=NORMAL, font=tkFont.Font(size=self.networkParams["visualize"]["lineFontSize"]))
        return line, label


    def drawRectangles(self):
        """draw rectangles corresponding to clients/routers"""
        rects = {}
        for label in self.rectCenters:
            if label in self.network.clients:
                fill = self.networkParams["visualize"]["clientColor"]
            elif label in self.network.routers:
                fill = self.networkParams["visualize"]["routerColor"]
            c = self.rectCenters[label]
            rect = self.canvas.create_rectangle(c[0]-self.boxWidth/6, c[1]-self.boxHeight/6,
                    c[0]+self.boxWidth/6, c[1]+self.boxHeight/6, fill=fill, activeoutline="green", activewidth=5)
            self.canvas.tag_bind(rect, '<1>', lambda event, label=label: self.inspectClientOrRouter(label))
            rects[label] = rect
            rectText = self.canvas.create_text(c[0], c[1], text=label, font=tkFont.Font(size=18, weight='bold'))
        return rects


    def inspectClientOrRouter(self, addr):
        """Handle a mouse click on a client or router"""
        if addr in self.network.clients:
            if self.clientFollowing:
                self.canvas.itemconfig(self.rects[self.clientFollowing], width=1)
            if self.clientFollowing != addr:
                self.clientFollowing = addr
                self.canvas.itemconfig(self.rects[addr], width=7)
            else:
                self.clientFollowing = None
        elif addr in self.network.routers:
            if self.routerFollowing:
                self.canvas.itemconfig(self.rects[self.routerFollowing], outline='black', width=1)
            if self.routerFollowing != addr:
                self.routerFollowing = addr
                self.canvas.itemconfig(self.rects[addr], width=7)
            else:
                self.routerFollowing = None


    def packetSend(self, packet, src, dst, latency):
        """Callback function used by Packet to tell the visualization that
           a packet is being sent"""
        if self.clientFollowing:
            if packet.dstAddr == self.clientFollowing and packet.isTraceroute():
                fillColor = "green"
            else:
                 return
        else:
            if packet.isTraceroute():
                fillColor = "DodgerBlue2"
            if packet.isRouting():
                fillColor = "red"
      
        latency = latency/self.latencyCorrection
        cx, cy = self.rectCenters[src]
        dx, dy = self.rectCenters[dst]
        packetRect = self.canvas.create_rectangle(cx-6, cy-6, cx+6, cy+6, fill=fillColor)
        distx, disty = dx-cx, dy-cy
        velocityx, velocityy = (distx*self.animateRate)/float(latency), (disty*self.animateRate/float(latency))
        numSteps, stepTime = latency / self.animateRate, self.animateRate/float(1000)
        thread.start_new_thread(self.movePacket, (packetRect, velocityx, velocityy, numSteps, stepTime))


    def movePacket(self, packetRect, vx, vy, numSteps, stepTime):
        """Animate a moving packet.  This should be run on a separate thread"""
        s = numSteps
        while s > 0:
            time.sleep(stepTime)
            self.canvas.move(packetRect, vx, vy)
            s -= 1
        self.canvas.delete(packetRect)


    def displayCurrentRoutes(self):
        """Display the current routes found by traceroute packets"""
        while True:
            routeString = self.network.getRouteString(labelIncorrect=False)
            pos = self.routeScrollbar.get()
            self.routeText.delete(1.0,END)
            self.routeText.insert(1.0, routeString)
            self.routeText.yview_moveto(pos[0])
            time.sleep(self.displayCurrentRoutesRate/float(1000))


    def displayCurrentDebug(self):
        """Display the debug string of the currently selected router"""
        while True:
            if self.routerFollowing:
                debugText = self.network.routers[self.routerFollowing].debugString()
                pos = self.debugScrollbar.get()
                self.debugText.delete(1.0,END)
                self.debugText.insert(END, debugText + "\n")
                self.debugText.yview_moveto(pos[0])
            time.sleep(self.displayCurrentDebugRate/float(1000))


    def visualizeChanges(self, change, target):
        """Make color and text changes to links upon additions, removals,
           and cost changes"""
        if change == "up":
            addr1, addr2, _, _, c12, c21 = target
            newLine, newLabel = self.drawLine(addr1, addr2, c12, c21)
            self.lines[(addr1, addr2)] = newLine
            self.linesLabel = newLabel
        elif change == "down":
            addr1, addr2, = target
            self.canvas.delete(self.lines[(addr1, addr2)])
            self.canvas.delete(self.lineLabels[(addr1, addr2)])


def main():
    """Main function parses command line arguments and
       runs the network visualizer"""
    if len(sys.argv) < 2:
        print "Usage: python visualize_network.py [networkSimulationFile.json] [DV|LS (router class, optional)]"
        return
    netCfgFilepath = sys.argv[1]
    visualizeParams = json.load(open(netCfgFilepath))
    routerClass = Router   # choose router algorithm
    if len(sys.argv) == 3: 
        if sys.argv[2] == "DV":
            routerClass = DVrouter
        elif sys.argv[2] == "LS":
            routerClass = LSrouter
    net = Network(netCfgFilepath, routerClass, visualize=True)
    root = Tk()
    root.wm_title("Commun. & Netw. PROJECT")
    app = App(root, net, visualizeParams)
    root.mainloop()


if __name__ == "__main__":
    main()
