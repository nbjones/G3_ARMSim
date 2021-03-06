#main file for ms3 ARM simulation
import serial
import argparse
import time
import binascii


class NavAlgorithm:
    """class containing the movement algorithm"""
    curr_sensor_frame = []
    curr_movement_comm = []
    curr_total_distance = [0, 0]
    last_total_distance = [0, 0]
    last_delta_distance = [0, 0]
    nav_state = "Stopped"
    little_more = False

    #movement macros
    bc_half_forward = bytes([0xBC, 0xA0, 0x20, 0xFF, 0xFF, 0x00])
    ba_15cm_forward = bytes([0xBA, 0xA0, 0x20, 0x0F, 0x0F, 0x00])  # 0.5ft
    ba_45cm_forward = bytes([0xBA, 0xA0, 0x20, 0x2D, 0x2D, 0x00])  # 1.5ft
    ba_90_left = bytes([0xBA, 0xE0, 0x20, 0x12, 0x12, 0x00])
    ba_90_right = bytes([0xBA, 0xA0, 0x60, 0x12, 0x12, 0x00])

    def alg_rcv_sensor_data(self, sensor_frame):
        self.curr_sensor_frame = sensor_frame

    def alg_get_next_move(self):
        time.sleep(0.2)
        if self.nav_state == "Stopped":
            self.curr_movement_comm = self.bc_half_forward
            self.nav_state = "Forward"
        elif self.nav_state == "Forward":
            if self.curr_sensor_frame[2] >= 0x5A and self.curr_sensor_frame[3] >= 0x5A:  # cleared on right side
                if self.little_more:
                    self.curr_movement_comm = self.ba_90_right
                    self.little_more = False
                    self.nav_state = "On_Corner"
                else:
                    self.little_more = True
                    self.curr_movement_comm = self.ba_45cm_forward
            elif self.curr_sensor_frame[1] <= 0x5A:  # we are in front of something
                self.curr_movement_comm = self.ba_90_left
                self.nav_state = "Against_Obstacle"
        elif self.nav_state == "Against_Obstacle":
            self.curr_movement_comm = self.bc_half_forward
            self.nav_state = "Forward"
        elif self.nav_state == "On_Corner":  # have to move forward one rover length
            if self.curr_sensor_frame[2] <= 0x5A and self.curr_sensor_frame[3] <= 0x5A:  # we are back against a wall
                self.curr_movement_comm = self.bc_half_forward
                self.nav_state = "Forward"
            else:
                self.curr_movement_comm = self.ba_45cm_forward
        return self.curr_movement_comm

    def alg_check_move_response(self, move_comm):
        print("Received:", "Movement data        ", binascii.hexlify(move_comm))
        self.curr_total_distance[0] = move_comm[2]
        self.curr_total_distance[1] = move_comm[3]

        self.last_delta_distance[0] = self.curr_total_distance[0] - self.last_total_distance[0]
        self.last_delta_distance[1] = self.curr_total_distance[1] - self.last_total_distance[1]

        self.last_total_distance[0] = self.curr_total_distance[0]
        self.last_total_distance[1] = self.curr_total_distance[1]
        if move_comm[1] == 0x01:  # we have stopped
            print("COMPLETE MOVE", self.curr_total_distance)
            self.curr_total_distance = [0, 0]
            self.last_total_distance = [0, 0]
            self.last_delta_distance = [0, 0]
            return True
        else:  # we are still moving
            print("DELTA DISTANCE", self.last_delta_distance)
            return False

    def get_side_delta(self):
        delta = self.curr_sensor_frame[2]/self.curr_sensor_frame[3]
        return delta


class SimCourse:
    """class containing simulation courses"""
    curr_sensor_frame = []
    movement_command_array = []
    current_place = 0
    total_commands = 0

    navAlg = NavAlgorithm()

    def __init__(self, filename):
        #file object for course data
        with open(filename) as course_file:
            for num, line in enumerate(course_file, 1):
                if line[0] != '#':
                    as_bytes = bytearray.fromhex(line.partition('#')[0].rstrip())
                    self.total_commands += 1
                    as_bytes.insert(0, 0xba)
                    checksum = (as_bytes[1]+as_bytes[2]+as_bytes[3]+as_bytes[4]) & 0x17
                    as_bytes.insert(5, checksum)
                    self.movement_command_array.append(as_bytes)
                    print("Read in movement command", binascii.hexlify(as_bytes))

    def rcv_sensor_data(self, sensor_frame):
        if args.use_algorithm:
            self.navAlg.alg_rcv_sensor_data(sensor_frame)
        else:
            self.curr_sensor_frame = sensor_frame

    def get_next_move(self):
        if args.use_algorithm:
            return self.navAlg.alg_get_next_move()
        else:
            return self.movement_command_array[self.current_place]

    def check_move_response(self, move_comm):
        """checks for the expected movement command"""
        move_complete = self.navAlg.alg_check_move_response(move_comm)
        if move_complete and args.use_algorithm is False:
            self.current_place += 1
        return move_complete


#let's make a state machine
def state0(course_obj):
    """initial state, request sensor data"""
    if args.no_sensors:
        return state1
    sensor_request = bytes([0xAA, 0x00, 0x00, 0x00, 0x00, 0x00])
    ser.write(sensor_request)
    time.sleep(0.1)
    print("Sent:    ", "Sensor gather request", binascii.hexlify(sensor_request))
    from_rover = ser.read(6)
    if from_rover.__len__() == 6:
        print("Received:", "Sensor data frame    ", binascii.hexlify(from_rover))
        if from_rover[0] == 0x01:
            print("FRONT:", int(from_rover[1]), "SIDE_FRONT", int(from_rover[2]), "SIDE_BACK:", int(from_rover[3]))
            course_obj.rcv_sensor_data(from_rover)
            if args.just_sensors:
                time.sleep(0.5)
                return state0
            else:
                return state1
        else:
            return state0
    else:
        return state0


def state1(course_obj):
    """send movement command, get ack"""
    next_move = course_obj.get_next_move()
    time.sleep(0.1)
    ser.write(next_move)
    print("Sent:    ", "Movement command     ", binascii.hexlify(next_move))
    from_rover = ser.read(6)
    if from_rover.__len__() == 6:
        if from_rover[0] == 0x03:
            print("Received:", "Command Acknowledged ", binascii.hexlify(from_rover))
            return state2
        else:
            return state1
    else:
        return state1


def state2(course_obj):
    """check for distance and eventually get finished move"""
    distance_request = bytes([0xBB, 0x00, 0x00, 0x00, 0x00, 0x00])
    ser.write(distance_request)
    from_rover = ser.read(6)
    if from_rover.__len__() == 6:
        if from_rover[0] == 0x04 and course_obj.check_move_response(from_rover):
            return state0
        else:
            return state2
    else:
        return state2


#time to parse command line args
parser = argparse.ArgumentParser(description='Simulate G3\'s ARM over UART')
parser.add_argument("port", help="port to open UART connection on")
parser.add_argument("command_file", help="file to read commands from")
parser.add_argument("-n", "--no_sensors", help="turn off gathering sensor data, only send moves", action="store_true")
parser.add_argument("-s", "--just_sensors", help="only gather sensor data", action="store_true")
parser.add_argument("-a", "--use_algorithm", help="use algorithm instead of text file", action="store_true")
args = parser.parse_args()

ser = serial.Serial(args.port, 19200, timeout=1)
if ser.isOpen():
    print("Opened port", args.port)

#object that will contain course data
course = SimCourse(args.command_file)

#initial state
state = state0

print("\n****SIMULATION BEGIN****")

#loop forever
while 1:
    if args.use_algorithm is False and (course.current_place == course.total_commands):
        print("End of simulation!")
        exit(0)
    state = state(course)

print("Simulation has exited upon failure.")
exit(-1)