from proxy.tlproxy import TransportLayerProxy
from packet import PacketManager
import config

import time
import socket
from threading import Thread
from scapy.all import *

DEBUG = config.DEBUG

class TCPProxy(TransportLayerProxy):

    INVALID_SESSION = -1

    def __init__(self, hostIP, packetManager: PacketManager, toAppServer:socket.socket, toClient):
        self.hostIP = hostIP
        self.packetManager = packetManager
        self.toAppServer = toAppServer
        self.toClient = toClient
        self.sessions = []
        self.ports = list(range(30000, 65536))

        collectorThread = Thread(target=self.garbageCollector, daemon=True)
        collectorThread.start()

    def getSessionByAddressInfo(self, src, sport, dst, dport):
        for session in self.sessions:
            if session['src'] == src and \
                session['sport'] == sport and \
                session['dst'] == dst and \
                session['dport'] == dport:
                return session

        return self.INVALID_SESSION

    def getSessionBySSport(self, sSport):
        for session in self.sessions:
            if session['sSport'] == sSport:
                return session

        return self.INVALID_SESSION

    def getNewPortNumber(self):
        return self.ports.pop(0)

    def newSession(self, address, src, sport, dst, dport):
        # add a new session
        new = {
            'clientAddress': address, 
            'src': src,
            'sport': sport,
            'sSport': self.getNewPortNumber(),
            'dst': dst,
            'dport': dport,
            'lastTime': time.time(), 
        }
        self.sessions.append(new)
        return new

    def close(self):
        # clean all sessions
        self.sessions.clear()

    def forwardToAppServer(self, data, clientAddress):
        src, dst = self.packetManager.getSrcIPandDstIP(data)
        sport, dport = self.packetManager.getSourceAndDstPort(data)

        session = self.getSessionByAddressInfo(src, sport, dst, dport)
        if session == self.INVALID_SESSION:
            # create a new session record
            session = self.newSession(clientAddress, src, sport, dst, dport)
        else:
            session['lastTime'] = time.time()

        # refactor the source port and source IP
        pck, _, _ = self.packetManager.refactorSrcAndDstIP(data, self.hostIP, None)
        pck, _, _ = self.packetManager.refactorSportAndDport(pck, session['sSport'], None)

        if DEBUG: print("----------------- TCP sSport: ", session['sSport'], "dst: ", dst, " dport: ", dport)
        
        try:
            self.toAppServer.sendto(pck, (dst, dport))
        except OSError as e:
            if DEBUG: print("Meet OSError message: ", e)

    def fowardToClient(self, data):
        # packet from App server
        src, dst = self.packetManager.getSrcIPandDstIP(data)
        sport, dport = self.packetManager.getSourceAndDstPort(data)

        session = self.getSessionBySSport(dport)
        # check the packet belongs to which exisiting session
        if session == self.INVALID_SESSION:
            return False
        elif session != self.getSessionByAddressInfo(session['src'], session['sport'], session['dst'], session['dport']):
            if DEBUG: print("Receive local Server packet")
            # packet does not belong to the VPN proxy
            return False
        else:
            session['lastTime'] = time.time()
            # refactor packet
            pck, _, _ = self.packetManager.refactorSrcAndDstIP(data, None, session['src'])
            pck, _, _ = self.packetManager.refactorSportAndDport(pck, None, session['sport'])

            self.toClient.sendto(pck, session['clientAddress'])
        
        return True

    def garbageCollector(self):
        while True:
            for session in self.sessions:
                if (time.time() - session["lastTime"]) > config.TCP_EXPIRE_TIME:
                    # expire if no update for 5 minutes
                    self.sessions.remove(session)
                    self.ports.append(session['sSport'])
                    if DEBUG: print('TCP Session: src:%s, sport:%s, dst:%s, dport:%s closed' 
                                    % session['src'], session['sport'], session['dst'], session['dport'])
            time.sleep(config.TCP_COLLECT_CYCLE)
