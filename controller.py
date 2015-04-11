from keyboard import *
from ioexpand import *
from threading import Thread
import socket

SOMFY_ADDR = ("198.0.0.228", 4999)

class TCPSender(Thread):
    def __init__(self, addr, data):
        Thread.__init__(self)
        self.addr = addr
        self.data = data
        self.daemon = True

    def run(self):
        print "sending", self.data, "to", self.addr
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(self.addr)
        time.sleep(0.1)
        print s.send(self.data)
        # without the sleep, it sometimes fails to work (weird)
        time.sleep(0.1)
        s.close()

class InsteonKeypad(Keypad):
    keys = {}

    def __init__(self, *args, **kwargs):
        Keypad.__init__(self, *args, **kwargs)

        for i in range(0,8):
            if not i in self.keys:
                self.keys[i] = {}

    def keyup(self, keynum):
        pass

    def keydown(self, keynum):
        self.keypress(keynum)

    def keypress(self, keynum):
        k = self.keys[keynum]
        if k.get("toggle", False):
            k["state"] = not k.get("state", False)

        group = k.get("group", [])
        if group:
            for g in group:
                self.keys[g]["state"] = False
                self.setled(g, False)
            k["state"] = True

        self.setled(keynum, k.get("state", False))

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

    keys = {key_lights: {"toggle": True},
            key_fan: {"toggle": True},
            key_left_up: {"group": [key_left_mid, key_left_down], "addr": SOMFY_ADDR, "data": "0102U\n"},
            key_left_mid: {"group": [key_left_up, key_left_down], "addr": SOMFY_ADDR, "data": "0102S\n"},
            key_left_down: {"group": [key_left_up, key_left_mid], "addr": SOMFY_ADDR, "data": "0102D\n"},

            key_right_up: {"group": [key_right_mid, key_right_down], "addr": SOMFY_ADDR, "data": "0101U\n"},
            key_right_mid: {"group": [key_right_up, key_right_down], "addr": SOMFY_ADDR, "data": "0101S\n"},
            key_right_down: {"group": [key_right_up, key_right_mid], "addr": SOMFY_ADDR, "data": "0101D\n"},
    }

def main():
    bus = smbus.SMBus(1)
    kp = Keypad1(MCP23017(bus, 0x20), 0, led=True)
    while 1:
       kp.poll()

if __name__=="__main__":
    main()
