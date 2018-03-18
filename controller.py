import argparse
import datetime
from keyboard import *
from ioexpand import *
from threading import Thread
import select
import socket
import base64
import requests
import threading
from vfd import VFD
import traceback
from elkm1 import ElkConnection, DISARM, ARM_STAY, ARM_AWAY, ARM_NIGHT
from motor import Motor, L293_1, L293_2, L293_ENABLE, L293_3, L293_4, L293_ENABLE2
from motorpot import MotorPot
import RPi.GPIO as IO

REMOTE_UPDATE_THRESH = 2
LOCAL_UPDATE_THRESH = 6
LOCAL_UPDATE_AFTER_MOVE_THRESH = 20

SOMFY_ADDR = ("198.0.0.228", 4999)
STEREO_ADDR = ("198.0.0.215", 80)
ELK_ADDR = ("198.0.0.219", 2601)

# read the isy credential from a file
# format is username:password
ISY_CREDS = open("isycreds","r").readline().strip()

glo_stereo_power_update = None
glo_stereo_volume_update = None
glo_stereo_power_state = False
glo_not_moving_count = 0

glo_arm_state_update = None
glo_elk = None

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

class HttpSender(Thread):
    def __init__(self, addr, url):
        Thread.__init__(self)
        self.addr = addr
        self.url = url

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(self.addr)
        time.sleep(0.1)

        auth = base64.b64encode(ISY_CREDS)

        s.send("GET %s HTTP/1.1\r\n" % self.url)
        #s.send("Authorization: Basic %s\r\n" % auth)
        #s.send("accept-encoding: identity\r\n")
        s.send("\r\n")

        #while True:
        #   x=s.recv(1024)
        #   print x
        #   if not x:
        #       break

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

        print datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "keynum %s pressed no_act=%s" % (keynum, str(no_act))

        if not no_act:
            if k.get("isy_node",None):
                if k.get("state", False):
                    ISYSender(k["isy_node"], "DON").start()
                else:
                    ISYSender(k["isy_node"], "DOF").start()

            if k.get("state",False) and k.get("addr", None):
                TCPSender(k["addr"], k["data"]).start()

            if k.get("http_addr",None):
                state = k.get("state",False)
                momentary = k.get("momentary", False)
                http_on = k.get("url_on", None)
                http_off = k.get("url_off", None)
                if state or momentary:
                    if http_on:
                        HttpSender(k["http_addr"], http_on).start()
                else:
                    if http_off:
                        HttpSender(k["http_addr"], http_off).start()

            if k.get("elk_set_arm",None) is not None:
                #print "ELK DISABLED!"
                glo_elk.set_arm(k["elk_set_arm"], k["elk_area"])

class Keypad1(InsteonKeypad):
    key_stereo_power = 7
    key_stereo_skip = 6

    key_left_up = 5
    key_left_mid = 3
    key_left_down = 1

    key_right_up = 4
    key_right_mid = 2
    key_right_down = 0

    keys = {
            key_stereo_power: {"toggle": True, "http_addr": STEREO_ADDR, "url_on": "/stereo/setPower?value=true", "url_off": "/stereo/setPower?value=false"},
            key_stereo_skip: {"momentary": True, "http_addr": STEREO_ADDR, "url_on": "/stereo/nextSong" },

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

    key_alarm_disarm = 7
    key_alarm_stay = 5
    key_alarm_away = 3

    key_lights = 1
    key_fan = 0

    keys = {
            key_by_up: {"group": [key_by_mid, key_by_down], "addr": SOMFY_ADDR, "data": "0103U0103U0103U0103U0103U\n"}, #"0103U\n"},
            key_by_mid: {"group": [key_by_up, key_by_down], "addr": SOMFY_ADDR, "data": "0103S0103S0103S0103S0103S\n"}, #"0103S\n"},
            key_by_down: {"group": [key_by_up, key_by_mid], "addr": SOMFY_ADDR, "data": "0103D0103D0103D0103D0103D\n"}, #"0103D\n"},

            key_alarm_disarm: {"group": [key_alarm_stay, key_alarm_away], "elk_area": 1, "elk_set_arm": DISARM},
            key_alarm_stay: {"group": [key_alarm_disarm, key_alarm_away], "elk_area": 1, "elk_set_arm": ARM_STAY},
            key_alarm_away: {"group": [key_alarm_disarm, key_alarm_stay], "elk_area": 1, "elk_set_arm": ARM_NIGHT},

            key_lights: {"toggle": True, "isy_node": "26717"},
            key_fan: {"toggle": True, "isy_node": "35771"},
            }

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

        self.commands = {"OFFICE_LIGHT_ON": {"keypad": keypads[1], "keynum": keypads[1].key_lights, "value": True},
                         "OFFICE_LIGHT_OFF": {"keypad": keypads[1], "keynum": keypads[1].key_lights, "value": False},
                         "OFFICE_FAN_ON": {"keypad": keypads[1], "keynum": keypads[1].key_fan, "value": True},
                         "OFFICE_FAN_OFF": {"keypad": keypads[1], "keynum": keypads[1].key_fan, "value": False}}

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

class StereoListenerThread(threading.Thread):
    def __init__(self, vfd):
        super(StereoListenerThread, self).__init__()
        self.daemon = True
        self.last_song = None
        self.last_artist = None
        self.last_power = None
        self.last_volume = None
        self.last_moving_time = time.time()
        self.vfd = vfd

    def run(self):
        global glo_stereo_power_update, glo_stereo_volume_update, glo_not_moving_count, glo_stereo_power_state

        while True:
            try:
                r = requests.get("http://%s/stereo/getSettings" % STEREO_ADDR[0])
                try:
                    r = r.json() 
                except TypeError:
                    r = r.json   # controller has older requests library??
                fmstation = r.get("fmstation","")
                if (fmstation.startswith("radio:")):
                    song = "     " + fmstation[6:-1] + "." + fmstation[-1]
                    artist = ""
                else:
                    song = r.get("song","").strip()
                    artist = r.get("artist","").strip()

                if not song:
                   song = ""
                if not artist:
                   artist = ""
                if (self.last_song != song) or (self.last_artist != artist):
                    #print song, artist
                    if self.vfd:
                        self.vfd.cls()
                        self.vfd.setPosition(0,0)
                        self.vfd.writeStr(song[:16])
                        self.vfd.setPosition(0,1)
                        self.vfd.writeStr(artist[:16])
                        self.last_song = song
                        self.last_artist = artist

                if self.last_power != r["power"]:
                    self.last_power = r["power"]
                    glo_stereo_power_update = r["power"]

                glo_stereo_power_state = r["power"]

                #if (r["volumeMoving"] and r["volumeSetPoint"] and (abs(r["volumeSetPoint"] - self.last_volume) >= REMOTE_UPDATE_THRESH)):
                #    glo_stereo_volume_update = r["volumeSetPoint"]
                #    self.last_volume = r["volumeSetPoint"]

                if r["volumeMoving"]:
                    glo_not_moving_count = 0
                else:
                    glo_not_moving_count += 1

                if (not r["volumeMoving"]) and ((not self.last_volume) or (abs(r["volumeCurrent"] - self.last_volume) >= REMOTE_UPDATE_THRESH)):
                    glo_stereo_volume_update = r["volumeCurrent"]
                    self.last_volume = r["volumeCurrent"]

                time.sleep(1)

            except:
                traceback.print_exc()
                try:
                    self.vfd.cls()
                    self.vfd.setPosition(0,0)
                    self.vfd.writeStr("Exception")
                except:
                    pass


class ElkListenerThread(threading.Thread, ElkConnection):
    def __init__(self, addr):
        threading.Thread.__init__(self)
        self.daemon = True

        ElkConnection.__init__(self, addr[0], addr[1])
        self.last_arm_state = None

    def run(self):
        self.bufferize()

    def arm_state(self, arm_state, arm_up, alarm_state):
        global glo_arm_state_update

        if arm_state[0] != self.last_arm_state:
            self.last_arm_state = arm_state[0]
            glo_arm_state_update = arm_state[0]

    def connected(self):
        self.s.write(self.gen_request_arm())
        
class ControllerMotorPot(MotorPot):
    def __init__(self, *args, **kwargs):
        self.lastValue = None
        self.lastSendTime = time.time()
        super(ControllerMotorPot, self).__init__(*args, **kwargs)

    def check_for_request(self):
        global glo_stereo_volume_update

        if glo_stereo_volume_update:
            print "receive", glo_stereo_volume_update

            if glo_not_moving_count<2:
                # Make sure the master has stopped moving for at least 2 seconds before we start responding to it,
                # otherwise we might respond to a movement-in-progress.
                #print "ignoring update, only", glo_not_moving_count, "not moving replies received"
                pass
            else:
                self.set(glo_stereo_volume_update)
                glo_stereo_volume_update = None

    def handle_value(self):
        global glo_not_moving_count

        if not (self.lastValue):
            self.lastValue = self.value

        delta = abs(self.value - self.lastValue)
        if (not self.moving) and (delta > LOCAL_UPDATE_THRESH):
            self.lastValue = self.value

            elapsed = time.time() - self.lastStopTime
            if (elapsed<=2) and (delta < LOCAL_UPDATE_AFTER_MOVE_THRESH):
                print "ignoring movement after update received", self.value
            else:
                print "send", self.value
                try:
                    glo_not_moving_count = 0
                    r = requests.get("http://%s/stereo/setVolume?volume=%d" % (STEREO_ADDR[0], self.value))
                except:
                    pass

class PowerSwitch(threading.Thread):
    def __init__(self, powerPin=4):
        threading.Thread.__init__(self)
        self.daemon = True

        self.powerPin = powerPin

        IO.setup(self.powerPin, IO.IN, pull_up_down=IO.PUD_UP)

        self.lastPowerState = IO.input(self.powerPin)

        self.start()

    def run(self):
        while True:
            self.powerState = IO.input(self.powerPin)
            if self.powerState and (not self.lastPowerState):
                self.power_pushed()
                time.sleep(1)   # lazy way of debouncing

            self.lastPowerState = self.powerState

            time.sleep(0.1)

    def power_pushed(self):
        print "power_pushed"
        if glo_stereo_power_state:
            try:
                r = requests.get("http://%s/stereo/setPower?value=false" % (STEREO_ADDR[0],))
            except:
                traceback.print_exc()
        else:
            try:
                r = requests.get("http://%s/stereo/setPower?value=true" % (STEREO_ADDR[0],))
            except:
                traceback.print_exc()


def parse_args():
    parser = argparse.ArgumentParser()

    defs = {"kp1": True,
            "kp2": True,
            "elk": True,
            "vfd": True,
            "powswitch": False,
            "motorpot": False,
            "stereo_url": None}

    _help = 'Disable first keypad (default: %s)' % defs['kp1']
    parser.add_argument(
        '-1', '--nokp1', dest='kp1', action='store_false',
        default=defs['kp1'],
        help=_help)

    _help = 'Disable second keypad (default: %s)' % defs['kp2']
    parser.add_argument(
        '-2', '--nokp2', dest='kp2', action='store_false',
        default=defs['kp2'],
        help=_help)

    _help = 'Disable elk (default: %s)' % defs['elk']
    parser.add_argument(
        '-k', '--noelk', dest='elk', action='store_false',
        default=defs['elk'],
        help=_help)

    _help = 'Disable vfd (default: %s)' % defs['vfd']
    parser.add_argument(
        '-f', '--novfd', dest='vfd', action='store_false',
        default=defs['vfd'],
        help=_help)

    _help = 'Enable motorpot (default: %s)' % defs['motorpot']
    parser.add_argument(
        '-m', '--motorpot', dest='motorpot', action='store_true',
        default=defs['motorpot'],
        help=_help)

    _help = 'Enable powerswitch on gpio4 (default: %s)' % defs['powswitch']
    parser.add_argument(
        '-p', '--powswitch', dest='powswitch', action='store_true',
        default=defs['powswitch'],
        help=_help)

    _help = 'URL of Stereo to control (default: %s)' % defs['stereo_url']
    parser.add_argument(
        '-S', '--stereo_url', dest='stereo_url', action='store',
        default=defs['stereo_url'],
        help=_help)

    args = parser.parse_args()

    return args

def main():
    global glo_stereo_power_update
    global glo_arm_state_update, glo_elk

    args = parse_args()

    kp1 = None
    kp2 = None
    listener = None
    elkListener = None
    glo_elk = None
    vfd = None
    motorpot = None
    powSwitch = None

    bus = smbus.SMBus(1)

    if (args.kp1):
        kp1 = Keypad1(MCP23017(bus, 0x20), 0, led=True)

    if (args.kp2):
        kp2 = Keypad2(MCP23017(bus, 0x21), 0, led=True)

    if (args.kp1) or (args.kp2):
        listener = UdpListener([kp1,kp2])

    if (args.vfd):
        vfd = VFD(0,0)

    if (args.motorpot):
        motorpot = ControllerMotorPot(bus, dirmult=1, verbose=False, motor_pin1=L293_3, motor_pin2=L293_4, motor_enable = L293_ENABLE2)

    if (args.powswitch):
        powSwitch = PowerSwitch()

    stereoListener = StereoListenerThread(vfd)
    stereoListener.start()

    if args.elk:
        elkListener = ElkListenerThread(ELK_ADDR)
        elkListener.start()
        glo_elk = elkListener

    while 1:
       if kp1:
           kp1.poll()

       if kp2:
           kp2.poll()

       if listener:
          listener.poll()   # polling makes me sad, but I'm also lazy... ought to thread this some time

       if kp1:
           # if the stereo listener detected a power button change, then update the button led
           if glo_stereo_power_update is not None:
               kp1.keypress(kp1.key_stereo_power, force_state=glo_stereo_power_update, no_act=True)
               glo_stereo_power_update = None

       if elkListener and kp2:
           if glo_arm_state_update is not None:
               if glo_arm_state_update == DISARM:
                   kp2.keypress(kp2.key_alarm_disarm, no_act=True)
               elif glo_arm_state_update == ARM_STAY:
                   kp2.keypress(kp2.key_alarm_stay, no_act=True)
               elif glo_arm_state_update in [ARM_NIGHT, ARM_AWAY]:
                   kp2.keypress(kp2.key_alarm_away, no_act=True)
               glo_arm_state_update = None

       time.sleep(0.01)

if __name__=="__main__":
    main()
