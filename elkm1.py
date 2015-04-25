import socket
import ssl
import sys
import time
import traceback

DISARM = 0
ARM_AWAY = 1
ARM_STAY = 2
ARM_STAY_INSTANT = 3
ARM_NIGHT = 4
ARM_NIGHT_INSTANT = 5
ARM_VACATION = 6
ARM_NEXT_AWAY = 7
ARM_NEXT_STAY = 8

ARM_UP_NOT_READY = 0
ARM_UP_READY = 1
ARM_UP_READY_FORCE = 2
ARM_UP_EXIT = 3
ARM_UP_FULLY = 4
ARM_UP_FORCE = 5
ARM_UP_BYPASS =6

ALARM_INACTIVE = '0'
ALARM_ENTRACE_DELAY = '1'
ALARM_ABORT_DELAY = '2'
ALARM_FIRE = '3'
ALARM_MEDICAL = '4'
ALARM_POLICE = '5'
ALARM_BURGLAR = '6'
ALARM_AUX1 = '7'
ALARM_AUX2 = '8'
ALARM_AUX3 = '9'
ALARM_AUX4 = ':'
ALARM_CO = ';'
ALARM_EMERGENCY = '<'
ALARM_FREEZE = '='
ALARM_GAS = '>'
ALARM_HEAT = '?'
ALARM_WATER = '@'
ALARM_FIRESUPER = 'A'
ALARM_FIREVERIFY = 'B'


class ElkConnection:
    def __init__(self, address=None, port=None):
        self.address = address
        self.port = port

        f = open("elkauth","r")
        self.username = f.readline().strip()
        self.password = f.readline().strip()
        self.code = f.readline().strip()

        self.last_arm_status = [0,0,0,0,0,0,0,0]

        self.socket_connected = False
        self.seen_connected = False
        self.sent_password = False
        self.buf = ''
        if address is not None:
            self.connect()

    def connect(self):
        self.socket_connected = False
        self.seen_connected = False
        self.sent_password = False
        self.buf = ''
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s = ssl.wrap_socket(self.s, ssl_version=ssl.PROTOCOL_TLSv1)
        self.s.connect((self.address, self.port))
        self.socket_connected = True

    def connected(self):
        pass

    def stupid_dump(self):
        while True:
            data = self.s.read()
            if len(data)>0:
                print len(data), data

    def calc_checksum(self, msg):
        chk = 0
        for x in msg:
            chk = (chk + ord(x)) & 0xFF;
        chk = 0x100 - chk
        return "%02X" % chk

    def send_username(self):
        print "sending username"
        self.s.write("%s\015\012" % self.username)

    def send_password(self):
        print "sending password"
        self.s.write("%s\015\012" % self.password)
        self.sent_password = True

    def gen_request_temperature(self,group,device):
        pkt="09st%X%02X00" % (group,device)
        pkt = pkt + self.calc_checksum(pkt)
        return pkt + "\015\012"

    def gen_set_arm(self, arming_level, area, code):
        while len(code)<6:
           code = '0' + code
        pkt="0Da%d%d%s00" % (arming_level, area, code)
        pkt = pkt + self.calc_checksum(pkt)
        return pkt + "\015\012"

    def gen_request_arm(self):
        pkt="1Eas00"
        pkt = pkt + self.calc_checksum(pkt)
        return pkt + "\015\012"

    def temperature(self, group, device, value):
        print "temperature", group, device, value

    def arm_state(self, arm_state, arm_up, alarm_state):
        print "arm_state", arm_state
        print "arm_up", arm_up
        print "alarm_state", alarm_state

    def read_sentence(self, sentence):
        sentence = sentence[:-2]
        if len(sentence)<6:
            return

        msg_len = sentence[0:2]
        type = sentence[2:4]

        if (not self.seen_connected) and (sentence.startswith("Elk-M1XEP: Login successful.")):
            # we saw a successful login message
            self.seen_connected = True
            self.connected()

#        if (not self.seen_connected) and (self.sent_password or self.password==None):
#            # we saw a sentence, and we sent our password
#            self.seen_connected = True
#            self.connected()

        if type=="ST":
            group = int(sentence[4],16)
            device = int(sentence[5:7],10)
            value = int(sentence[7:10],10)-60
            self.temperature(group, device, value)
        elif type=="AS":
            if len(sentence)<32:
                print "malformed sentence", sentence
            else:
                arm_status = sentence[4:12]
                arm_up = sentence[12:20]
                alarm_state = sentence[20:28]

                self.last_arm_state = [int(x) for x in arm_status]

                self.arm_state( [int(x) for x in arm_status],
                                  [int(x) for x in arm_up],
                                  [x for x in alarm_state] )
        else:
            #print sentence
            pass

    def bufferize(self):
        self.buf='';
        while True:
            while not self.socket_connected:
                try:
                    print "ELK: (re)connecting"
                    self.connect()
                    print "ELK: (re)connected"
                except:
                    print "ELK: connection failed"
                    traceback.print_exc()

            try:
                 self.bufferize_once()
            except:
                 print "ELK: exception in bufferize_once, sleeping 30s and reconnecting"
                 time.sleep(30) # let's not hammer the Elk too hard if we're being stupid and crashing
                 self.socket_connected = False
                 traceback.print_exc()

    def bufferize_once(self):
        data = self.s.read()
        for char in data:
            self.buf = self.buf + char
            if self.buf.endswith("Username:"):
                self.send_username()
                self.buf=''
            elif self.buf.endswith("Password:"):
                self.send_password()
                self.buf=''
            elif self.buf.endswith("\015\012"):
                self.read_sentence(self.buf)
                self.buf=''

    def set_arm(self, arming_level, area):
        if (arming_level!=DISARM) and (self.last_arm_status[area-1] != arming_level):
            # if it's armed in some other state, then disarm it first
            self.s.send(self.gen_set_arm(DISARM, area, self.code))
        self.s.send(self.gen_set_arm(arming_level, area, self.code))

class ElkTemperaturePrinter(ElkConnection):
    def __init__(self, address=None, port=None):
        ElkConnection.__init__(self, address, port)

    def connected(self):
        print "connected"
        self.s.write(self.gen_request_temperature(0,4))
        self.s.write(self.gen_request_temperature(0,5))

class ElkArmStatePrinter(ElkConnection):
    def __init__(self, address=None, port=None):
        ElkConnection.__init__(self, address, port)

    def connected(self):
        print "connected"
        self.s.write(self.gen_request_arm())

def checksum_test_pkt(pkt):
    correct_sum = pkt[-2:]
    pkt = pkt[:-2]

    chk = ElkConnection().calc_checksum(pkt)
    if (correct_sum != chk):
        print "checksum test fail, pkt=%s, correct_sum=%s, calc_sum=%s" % (pkt, correct_sum, chk)

def checksum_test():
    checksum_test_pkt("0DCV0100123003C")
    checksum_test_pkt("08cv0100FE")
    checksum_test_pkt("13TR01200726875000000")
    checksum_test_pkt("11KF01C200000000087")
    checksum_test_pkt("16KA12345678111111110081")

def main():
    elk = ElkArmStatePrinter("198.0.0.219", 2601)
    elk.bufferize()

if __name__ == "__main__":
    main()
