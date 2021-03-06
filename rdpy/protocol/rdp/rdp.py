#
# Copyright (c) 2014 Sylvain Peyrefitte
#
# This file is part of rdpy.
#
# rdpy is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

"""
Use to manage RDP stack in twisted
"""

from rdpy.network import layer
from rdpy.base.error import CallPureVirtualFuntion, InvalidValue
import pdu.layer
import pdu.data
import pdu.caps
import rdpy.base.log as log
import tpkt, x224, mcs, gcc

class RDPClientController(pdu.layer.PDUClientListener):
    """
    Manage RDP stack as client
    """
    def __init__(self):
        #list of observer
        self._clientObserver = []
        #PDU layer
        self._pduLayer = pdu.layer.Client(self)
        #multi channel service
        self._mcsLayer = mcs.Client(self._pduLayer)
        #transport pdu layer
        self._x224Layer = x224.Client(self._mcsLayer)
        #transport packet (protocol layer)
        self._tpktLayer = tpkt.TPKT(self._x224Layer, self._pduLayer)
        #is pdu layer is ready to send
        self._isReady = False
        
    def getProtocol(self):
        """
        @return: return Protocol layer for twisted
        In case of RDP TPKT is the Raw layer
        """
        return self._tpktLayer
    
    def getColorDepth(self):
        """
        @return: color depth set by the server (15, 16, 24)
        """
        return self._pduLayer._serverCapabilities[pdu.caps.CapsType.CAPSTYPE_BITMAP].capability.preferredBitsPerPixel.value
    
    def getKeyEventUniCodeSupport(self):
        """
        @return: True if server support unicode input
        """
        return self._pduLayer._serverCapabilities[pdu.caps.CapsType.CAPSTYPE_INPUT].capability.inputFlags.value & pdu.caps.InputFlags.INPUT_FLAG_UNICODE
        
    def setPerformanceSession(self):
        """
        Set particular flag in RDP stack to avoid wall-paper, theme, menu animation etc...
        """
        self._pduLayer._info.extendedInfo.performanceFlags.value = pdu.data.PerfFlag.PERF_DISABLE_WALLPAPER | pdu.data.PerfFlag.PERF_DISABLE_MENUANIMATIONS | pdu.data.PerfFlag.PERF_DISABLE_CURSOR_SHADOW | pdu.data.PerfFlag.PERF_DISABLE_THEMING | pdu.data.PerfFlag.PERF_DISABLE_FULLWINDOWDRAG
        
    def setScreen(self, width, height):
        """
        Set screen dim of session
        @param width: width in pixel of screen
        @param height: height in pixel of screen
        """
        #set screen definition in MCS layer
        self._mcsLayer._clientSettings.getBlock(gcc.MessageType.CS_CORE).desktopHeight.value = height
        self._mcsLayer._clientSettings.getBlock(gcc.MessageType.CS_CORE).desktopWidth.value = width
        
    def setUsername(self, username):
        """
        Set the username for session
        @param username: username of session
        """
        #username in PDU info packet
        self._pduLayer._info.userName.value = username
        
    def setPassword(self, password):
        """
        Set password for session
        @param password: password of session
        """
        self.setAutologon()
        self._pduLayer._info.password.value = password
        
    def setDomain(self, domain):
        """
        Set the windows domain of session
        @param domain: domain of session
        """
        self._pduLayer._info.domain.value = domain
        
    def setAutologon(self):
        """
        @summary: enable autologon
        """
        self._pduLayer._info.flag |= pdu.data.InfoFlag.INFO_AUTOLOGON
        
    def addClientObserver(self, observer):
        """
        Add observer to RDP protocol
        @param observer: new observer to add
        """
        self._clientObserver.append(observer)
        
    def removeClientObserver(self, observer):
        """
        Remove observer to RDP protocol stack
        @param observer: observer to remove
        """
        for i in range(0, len(self._clientObserver)):
            if self._clientObserver[i] == observer:
                del self._clientObserver[i]
                return
        
    def onUpdate(self, rectangles):
        """
        Call when a bitmap data is received from update PDU
        @param rectangles: [pdu.BitmapData] struct
        """
        for observer in self._clientObserver:
            #for each rectangle in update PDU
            for rectangle in rectangles:
                observer.onUpdate(rectangle.destLeft.value, rectangle.destTop.value, rectangle.destRight.value, rectangle.destBottom.value, rectangle.width.value, rectangle.height.value, rectangle.bitsPerPixel.value, rectangle.flags.value & pdu.data.BitmapFlag.BITMAP_COMPRESSION, rectangle.bitmapDataStream.value)
                
    def onReady(self):
        """
        Call when PDU layer is connected
        """
        self._isReady = True
        #signal all listener
        for observer in self._clientObserver:
            observer.onReady()
            
    def onClose(self):
        """
        Event call when RDP stack is closed
        """
        self._isReady = False
        for observer in self._clientObserver:
            observer.onClose()
    
    def sendPointerEvent(self, x, y, button, isPressed):
        """
        send pointer events
        @param x: x position of pointer
        @param y: y position of pointer
        @param button: 1 or 2 or 3
        @param isPressed: true if button is pressed or false if it's released
        """
        if not self._isReady:
            return

        try:
            event = pdu.data.PointerEvent()
            if isPressed:
                event.pointerFlags.value |= pdu.data.PointerFlag.PTRFLAGS_DOWN
            
            if button == 1:
                event.pointerFlags.value |= pdu.data.PointerFlag.PTRFLAGS_BUTTON1
            elif button == 2:
                event.pointerFlags.value |= pdu.data.PointerFlag.PTRFLAGS_BUTTON2
            elif button == 3:
                event.pointerFlags.value |= pdu.data.PointerFlag.PTRFLAGS_BUTTON3
            else:
                event.pointerFlags.value |= pdu.data.PointerFlag.PTRFLAGS_MOVE
            
            #position
            event.xPos.value = x
            event.yPos.value = y
            
            #send proper event
            self._pduLayer.sendInputEvents([event])
            
        except InvalidValue:
            log.info("try send pointer event with incorrect position")
            
    def sendKeyEventScancode(self, code, isPressed):
        """
        Send a scan code to RDP stack
        @param code: scan code
        @param isPressed: True if key is pressed and false if it's released
        """
        if not self._isReady:
            return
        
        try:
            event = pdu.data.ScancodeKeyEvent()
            event.keyCode.value = code
            if isPressed:
                event.keyboardFlags.value |= pdu.data.KeyboardFlag.KBDFLAGS_DOWN
            else:
                event.keyboardFlags.value |= pdu.data.KeyboardFlag.KBDFLAGS_RELEASE
            
            #send event
            self._pduLayer.sendInputEvents([event])
            
        except InvalidValue:
            log.info("try send bad key event")
            
    def sendKeyEventUnicode(self, code, isPressed):
        """
        Send a scan code to RDP stack
        @param code: unicode
        @param isPressed: True if key is pressed and false if it's released
        """
        if not self._isReady:
            return
        
        try:
            event = pdu.data.UnicodeKeyEvent()
            event.unicode.value = code
            if not isPressed:
                event.keyboardFlags.value |= pdu.data.KeyboardFlag.KBDFLAGS_RELEASE
            
            #send event
            self._pduLayer.sendInputEvents([event])
            
        except InvalidValue:
            log.info("try send bad key event")
            
    def sendRefreshOrder(self, left, top, right, bottom):
        """
        Force server to resend a particular zone
        @param left: left coordinate
        @param top: top coordinate
        @param right: right coordinate
        @param bottom: bottom coordinate
        """
        refreshPDU = pdu.data.RefreshRectPDU()
        rect = pdu.data.InclusiveRectangle()
        rect.left.value = left
        rect.top.value = top
        rect.right.value = right
        rect.bottom.value = bottom
        refreshPDU.areasToRefresh._array.append(rect)
        self._pduLayer.sendDataPDU(refreshPDU)
            
    def close(self):
        """
        Close protocol stack
        """
        self._pduLayer.close()

class RDPServerController(pdu.layer.PDUServerListener):
    """
    Controller use in server side mode
    """               
    def __init__(self, privateKeyFileName, certificateFileName, colorDepth):
        """
        @param privateKeyFileName: file contain server private key
        @param certficiateFileName: file that contain public key
        @param colorDepth: 15, 16, 24
        """
        self._isReady = False
        #list of observer
        self._serverObserver = []
        #build RDP protocol stack
        self._pduLayer = pdu.layer.Server(self)
        #multi channel service
        self._mcsLayer = mcs.Server(self._pduLayer)
        #transport pdu layer
        self._x224Layer = x224.Server(self._mcsLayer, privateKeyFileName, certificateFileName)
        #transport packet (protocol layer)
        self._tpktLayer = tpkt.TPKT(self._x224Layer, self._pduLayer)
        #set color depth of session
        self.setColorDepth(colorDepth)
        
    def close(self):
        """
        Close protocol stack
        """
        self._pduLayer.close()
        
    def getProtocol(self):
        """
        @return: the twisted protocol layer
        in RDP case is TPKT layer
        """
        return self._tpktLayer
    
    def getUsername(self):
        """
        Must be call after on ready event else always empty string
        @return: username send by client may be an empty string
        """
        return self._pduLayer._info.userName.value
    
    def getPassword(self):
        """
        Must be call after on ready event else always empty string
        @return: password send by client may be an empty string
        """
        return self._pduLayer._info.password.value
    
    def getDomain(self):
        """
        Must be call after on ready event else always empty string
        @return: domain send by client may be an empty string
        """
        return self._pduLayer._info.domain.value
    
    def getCredentials(self):
        """
        Must be call after on ready event else always empty string
        @return: tuple(domain, username, password)
        """
        return (self.getDomain(), self.getUsername(), self.getPassword())
    
    def getColorDepth(self):
        """
        @return: color depth define by server
        """
        return self._colorDepth
    
    def getScreen(self):
        """
        @return: tuple(width, height) of client asked screen
        """
        bitmapCap = self._pduLayer._clientCapabilities[pdu.caps.CapsType.CAPSTYPE_BITMAP].capability
        return (bitmapCap.desktopWidth.value, bitmapCap.desktopHeight.value)
    
    def addServerObserver(self, observer):
        """
        Add observer to RDP protocol
        @param observer: new observer to add
        """
        self._serverObserver.append(observer)
        
    def setColorDepth(self, colorDepth):
        """
        Set color depth of session
        if PDU stack is already connected send a deactive-reactive sequence
        @param colorDepth: depth of session (15, 16, 24)
        """
        self._colorDepth = colorDepth
        self._pduLayer._serverCapabilities[pdu.caps.CapsType.CAPSTYPE_BITMAP].capability.preferredBitsPerPixel.value = colorDepth
        if self._isReady:
            #restart connection sequence
            self._isReady = False
            self._pduLayer.sendPDU(pdu.data.DeactiveAllPDU())
            
    def setKeyEventUnicodeSupport(self):
        """
        Enable key event in unicode format
        """
        self._pduLayer._serverCapabilities[pdu.caps.CapsType.CAPSTYPE_INPUT].capability.inputFlags.value |= pdu.caps.InputFlags.INPUT_FLAG_UNICODE
    
    def onReady(self):
        """
        RDP stack is now ready
        """
        self._isReady = True
        for observer in self._serverObserver:
            observer.onReady()
            
    def onClose(self):
        """
        Event call when RDP stack is closed
        """
        self._isReady = False
        for observer in self._serverObserver:
            observer.onClose()
            
    def onSlowPathInput(self, slowPathInputEvents):
        """
        Event call when slow path input are available
        @param slowPathInputEvents: [data.SlowPathInputEvent]
        """
        for observer in self._serverObserver:
            for event in slowPathInputEvents:
                #scan code
                if event.messageType.value == pdu.data.InputMessageType.INPUT_EVENT_SCANCODE:
                    observer.onKeyEventScancode(event.slowPathInputData.keyCode.value, not (event.slowPathInputData.keyboardFlags.value & pdu.data.KeyboardFlag.KBDFLAGS_RELEASE))
                #unicode
                elif event.messageType.value == pdu.data.InputMessageType.INPUT_EVENT_UNICODE:
                    observer.onKeyEventUnicode(event.slowPathInputData.unicode.value, not (event.slowPathInputData.keyboardFlags.value & pdu.data.KeyboardFlag.KBDFLAGS_RELEASE))
                #mouse event    
                elif event.messageType.value == pdu.data.InputMessageType.INPUT_EVENT_MOUSE:
                    isPressed = event.slowPathInputData.pointerFlags.value & pdu.data.PointerFlag.PTRFLAGS_DOWN
                    button = 0
                    if event.slowPathInputData.pointerFlags.value & pdu.data.PointerFlag.PTRFLAGS_BUTTON1:
                        button = 1
                    elif event.slowPathInputData.pointerFlags.value & pdu.data.PointerFlag.PTRFLAGS_BUTTON2:
                        button = 2
                    elif event.slowPathInputData.pointerFlags.value & pdu.data.PointerFlag.PTRFLAGS_BUTTON3:
                        button = 3
                    observer.onPointerEvent(event.slowPathInputData.xPos.value, event.slowPathInputData.yPos.value, button, isPressed)
    
    def sendUpdate(self, destLeft, destTop, destRight, destBottom, width, height, bitsPerPixel, isCompress, data):
        """
        send bitmap update
        @param destLeft: xmin position
        @param destTop: ymin position
        @param destRight: xmax position because RDP can send bitmap with padding
        @param destBottom: ymax position because RDP can send bitmap with padding
        @param width: width of bitmap
        @param height: height of bitmap
        @param bitsPerPixel: number of bit per pixel
        @param isCompress: use RLE compression
        @param data: bitmap data
        """
        if not self._isReady:
            return
        bitmapData = pdu.data.BitmapData(destLeft, destTop, destRight, destBottom, width, height, bitsPerPixel, data)
        if isCompress:
            bitmapData.flags.value = pdu.data.BitmapFlag.BITMAP_COMPRESSION
        
        self._pduLayer.sendBitmapUpdatePDU([bitmapData])

class ClientFactory(layer.RawLayerClientFactory):
    """
    Factory of Client RDP protocol
    """
    def connectionLost(self, tpktLayer):
        #retrieve controller
        x224Layer = tpktLayer._presentation
        mcsLayer = x224Layer._presentation
        pduLayer = mcsLayer._channels[mcs.Channel.MCS_GLOBAL_CHANNEL]
        controller = pduLayer._listener
        controller.onClose()
        
    def buildRawLayer(self, addr):
        """
        Function call from twisted and build rdp protocol stack
        @param addr: destination address
        """
        controller = RDPClientController()
        self.buildObserver(controller, addr)
        return controller.getProtocol()
    
    def buildObserver(self, controller, addr):
        """
        Build observer use for connection
        @param controller: RDPClientController
        @param addr: destination address
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "buildObserver", "ClientFactory"))

class ServerFactory(layer.RawLayerServerFactory):
    """
    Factory of Server RDP protocol
    """
    def __init__(self, privateKeyFileName, certificateFileName, colorDepth):
        """
        @param privateKeyFileName: file contain server private key
        @param certficiateFileName: file that contain public key
        @param colorDepth: color depth of session
        """
        self._privateKeyFileName = privateKeyFileName
        self._certificateFileName = certificateFileName
        self._colorDepth = colorDepth
    
    def connectionLost(self, tpktLayer):
        #retrieve controller
        x224Layer = tpktLayer._presentation
        mcsLayer = x224Layer._presentation
        pduLayer = mcsLayer._channels[mcs.Channel.MCS_GLOBAL_CHANNEL]
        controller = pduLayer._listener
        controller.onClose()
    
    def buildRawLayer(self, addr):
        """
        Function call from twisted and build rdp protocol stack
        @param addr: destination address
        """
        controller = RDPServerController(self._privateKeyFileName, self._certificateFileName, self._colorDepth)
        self.buildObserver(controller, addr)
        return controller.getProtocol()
    
    def buildObserver(self, controller, addr):
        """
        Build observer use for connection
        @param controller: RDP stack controller
        @param addr: destination address
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "buildObserver", "ServerFactory")) 
        
class RDPClientObserver(object):
    """
    Class use to inform all RDP event handle by RDPY
    """
    def __init__(self, controller):
        """
        @param controller: RDP controller use to interact with protocol
        """
        self._controller = controller
        self._controller.addClientObserver(self)
        
    def onReady(self):
        """
        Stack is ready and connected
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "onReady", "RDPClientObserver")) 
    
    def onClose(self):
        """
        Stack is closes
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "onClose", "RDPClientObserver")) 
    
    def onUpdate(self, destLeft, destTop, destRight, destBottom, width, height, bitsPerPixel, isCompress, data):
        """
        Notify bitmap update
        @param destLeft: xmin position
        @param destTop: ymin position
        @param destRight: xmax position because RDP can send bitmap with padding
        @param destBottom: ymax position because RDP can send bitmap with padding
        @param width: width of bitmap
        @param height: height of bitmap
        @param bitsPerPixel: number of bit per pixel
        @param isCompress: use RLE compression
        @param data: bitmap data
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "onUpdate", "RDPClientObserver"))
    
class RDPServerObserver(object):
    """
    Class use to inform all RDP event handle by RDPY
    """
    def __init__(self, controller):
        """
        @param controller: RDP controller use to interact with protocol
        """
        self._controller = controller
        self._controller.addServerObserver(self)
        
    def onReady(self):
        """
        Stack is ready and connected
        May be called after an setColorDepth too
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "onReady", "RDPServerObserver"))
    
    def onClose(self):
        """
        Stack is closes
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "onClose", "RDPClientObserver")) 
    
    def onKeyEventScancode(self, code, isPressed):
        """
        Event call when a keyboard event is catch in scan code format
        @param code: scan code of key
        @param isPressed: True if key is down
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "onKeyEventScanCode", "RDPServerObserver"))
    
    def onKeyEventUnicode(self, code, isPressed):
        """
        Event call when a keyboard event is catch in unicode format
        @param code: unicode of key
        @param isPressed: True if key is down
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "onKeyEventUnicode", "RDPServerObserver"))
    
    def onPointerEvent(self, x, y, button, isPressed):
        """
        Event call on mouse event
        @param x: x position
        @param y: y position
        @param button: 1, 2 or 3 button
        @param isPressed: True if mouse button is pressed
        """
        raise CallPureVirtualFuntion("%s:%s defined by interface %s"%(self.__class__, "onPointerEvent", "RDPServerObserver"))