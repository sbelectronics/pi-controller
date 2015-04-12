from keyboard import *
from ioexpand import *
from threading import Thread
import select
import socket
import base64

SOMFY_ADDR = ("198.0.0.228", 4999)

# read the isy credential from a file
# format is username:password
ISY_CREDS = open("isycreds","r").readline().strip()

"""
import controller
controller.ISYSender("26717", "DOF").start()
"""

class TCPSender(Thread):
    def __init__(self, addr, data):
        Thread.__init__(self)
        self.addr = addr
        self.data = data
        self.daemon = True

    def run(self):
        #print "sending", self.data, "to", self.addr
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(self.addr)
        time.sleep(0.1)
        s.send(self.data)
        # without the sleep, it sometimes fails to work (weird)
        time.sleep(0.1)
        s.close()

class ISYSender(Thread):
    def __init__(self, node, cmd):
        Thread.__init__(self)
        self.addr = ("198.0.0.220", 80)
        self.node = node
        self.cmd = cmd

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(self.addr)
        time.sleep(0.1)

        auth = base64.b64encode(ISY_CREDS)

        url = "/rest/nodes/%s/cmd/%s" % (str(self.node), str(self.cmd))
        s.send("GET %s HTTP/1.1\r\n" % url)
        s.send("Authorization: Basic %s\r\n" % auth)
        s.send("accept-encoding: identity\r\n")
        s.send("\r\n")

        #while True:
        #   x=s.recv(1024)
        #   print x
        #   if not x:
        #       break

        s.close()

class InsteonKeypad(Keypad):
    keys = {}

    """ 'keys' tells us what to do when a key is pressed.

           'toggle': each press should toggle the state from on-to-off
           'group': a list of other keys that this key should participate with.
                    When the key is pressed, it turns the other keys off.
           'addr': a (hostname, port) to send a TCP message to
           'date': the TCP message to send to 'addr'
           'isy_node': an isy node number. DON will be sent when the button
                       turns on and DOF will be sent when the button turns
                       off.
    """

    def __init__(self, *args, **kwargs):
        Keypad.__init__(self, *args, **kwargs)

        for i in range(0,8):
            if not i in self.keys:
                self.keys[i] = {}

    def keyup(self, keynum):
        pass

    def keydown(self, keynum):
        self.keypress(keynum)

    def keypress(self, keynum, no_act=False, force_state=None):
        k = self.keys[keynum]

        if force_state is not None:
            k["state"] = force_state
        else:
            if k.get("toggle", False):
                k["state"] = not k.get("state", False)

        group = k.get("group", [])
        if group:
            for g in group:
                self.keys[g]["state"] = False
                self.setled(g, False)
            k["state"] = True

        self.setled(keynum, k.get("state", False))

        if not no_act:
            if k.get("isy_node",None):
                if k.get("state", False):
                    ISYSender(k["isy_node"], "DON").start()
                else:
                    ISYSender(k["isy_node"], "DOF").start()

            if k.get("state",False) and k.get("addr", None):
                TCPSender(k["addr"], k["data"]).start()

class Keypad1(InsteonKeypad):
    key_lights = 7
    key_fan = 6

    key_left_up = 5
    key_left_mid = 3
    key_left_down = 1

    key_right_up = 4
    key_right_mid = 2
    key_right_down = 0

    keys = {key_lights: {"toggle": True, "isy_node": "26717"},
            key_fan: {"toggle": True, "isy_node": "35771"},
            key_left_up: {"group": [key_left_mid, key_left_down], "addr": SOMFY_ADDR, "data": "0102U\n"},
            key_left_mid: {"group": [key_left_up, key_left_down], "addr": SOMFY_ADDR, "data": "0102S\n"},
            key_left_down: {"group": [key_left_up, key_left_mid], "addr": SOMFY_ADDR, "data": "0102D\n"},

            key_right_up: {"group": [key_right_mid, key_right_down], "addr": SOMFY_ADDR, "data": "0101U\n"},
            key_right_mid: {"group": [key_right_up, key_right_down], "addr": SOMFY_ADDR, "data": "0101S\n"},
            key_right_down: {"group": [key_right_up, key_right_mid], "addr": SOMFY_ADDR, "data": "0101D\n"},
    }

class Keypad2(InsteonKeypad):
    key_by_up = 6
    key_by_mid = 4
    key_by_down = 2

    keys = {
            key_by_up: {"group": [key_by_mid, key_by_down], "addr": SOMFY_ADDR, "data": "0103U\n"},
            key_by_mid: {"group": [key_by_up, key_by_down], "addr": SOMFY_ADDR, "data": "0103S\n"},
            key_by_down: {"group": [key_by_up, key_by_mid], "addr": SOMFY_ADDR, "data": "0103D\n"},}

class UdpListener:
    """ We want the keypad to be able to respond to scenes on the ISY, so
        we setup a back-channel via UDP. When something on the ISY changes, it'll
        send a message to port 1776 telling us what to do. Then we update our
        LEDs in response.
    """

    def __init__(self, keypads):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(('',1776))

        """ self.commands tells us which key to push when the UDP packet comes in """

        self.commands = {"OFFICE_LIGHT_ON": {"keypad": keypads[0], "keynum": keypads[0].key_lights, "value": True},
                         "OFFICE_LIGHT_OFF": {"keypad": keypads[0], "keynum": keypads[0].key_lights, "value": False},
                         "OFFICE_FAN_ON": {"keypad": keypads[0], "keynum": keypads[0].key_fan, "value": True},
                         "OFFICE_FAN_OFF": {"keypad": keypads[0], "keynum": keypads[0].key_fan, "value": False}}

    def poll(self):
        while True:
           ready_read, ready_write, ready_error = select.select([self.socket], [], [], 0)
           if not (self.socket in ready_read):
               return

           msg =  self.socket.recv(1024)
           action = self.commands.get(msg, None)
           # print "UDP msg", msg
           if action:
               keypad=action["keypad"]
               keynum=action["keynum"]
               value=action["value"]
               keypad.keypress(keynum, force_state=value, no_act=True)

def main():
    bus = smbus.SMBus(1)
    kp1 = Keypad1(MCP23017(bus, 0x20), 0, led=True)
    kp2 = Keypad2(MCP23017(bus, 0x21), 0, led=True)
    listener = UdpListener([kp1])
    while 1:
       kp1.poll()
       kp2.poll()
       listener.poll()   # polling makes me sad, but I'm also lazy... ought to thread this some time
       time.sleep(0.01)

if __name__=="__main__":
    main()
