
# Simple flow class
class SharkPacket:

    def __init__(self, line):
        self.data = {}

        line = line.strip()
        items = line.split()

        name = ['start_time', 'src_ip', 'dst_ip', 'protocol', 'length',
                'src_port', 'dst_port']

        protocol = items[5]
        try:
            f = getattr(self, protocol)
            f(name, items)
        except Exception as e:
            self.default(name, items)

    # Get an item
    def __getitem__(self,index):
        return self.data[index]

    def identifier(self):
        return (self.data['src_ip'], self.data['dst_ip'], self.data['protocol'])

    # Default protocol handler
    def default(self, name, items):
        a = 0
        for i in [1,2,4,5,6,7,8]:
            self.data[name[a]] = items[i]
            a += 1
        self.data[name[0]] = float(self.data[name[0]])
        self.data[name[4]] = int(self.data[name[4]])
        self.data[name[5]] = int(self.data[name[5]])
        self.data[name[6]] = int(self.data[name[6]])

    # ARP protocol
    def ARP(self, name, items):
        a = 0
        for i in [1,2,4,5,6]:
            self.data[name[a]] = items[i]
            a += 1
        self.data[name[0]] = float(self.data[name[0]])
        self.data[name[4]] = int(self.data[name[4]])
        self.data['src_port'] = 0
        self.data['dst_port'] = 0

# A flow record
class SharkFlow:

    def __init__(self, rec):
        self.src_ip = rec['src_ip']
        self.dst_ip = rec['dst_ip']
        self.start_time = rec['start_time']
        self.last_time = rec['start_time']
        self.protocol = rec['protocol']
        self.size = rec['length']
        self.src_port = rec['src_port']
        self.dst_port = rec['dst_port']
        self.packets = 1

    def is_timeout(self, time, timeout):
        return time - self.last_time > timeout

    def update(self, time, size=0):
        self.last_time = time
        self.size += size
        self.packets += 1

    def get_sample(self):
        from flow import FlowRecord
        f = FlowRecord()

        f.start_time = self.start_time
        f.duration = self.last_time - self.start_time

        f.protocol = self.protocol.lower()
        f.src_port = self.src_port
        f.dest_port = self.dst_port
        f.src_ip = self.src_ip
        f.dest_ip = self.dst_ip

        f.bidirectional = "->"

        f.state = ""
        f.sTos = 0
        f.dTos = 0

        f.total_pckts = self.packets
        f.total_bytes = self.size
        f.total_srcbytes = self.size

        return f.make_sample()

    def output(self):
        return ' '.join([str(self.start_time), self.src_ip, self.dst_ip, str(self.src_port), str(self.dst_port), self.protocol, str(self.size), str(self.last_time - self.start_time)]) + '\n'

# The netflow generator
class NetflowGenerator:

    def __init__(self, timeout=10.):
        self.timeout = float(timeout) / 1000

    # Start generation
    def start(self, algorithm=None, dest=None):
        self.packets = 0
        self.open = 0
        self.complete = 0

        self.open_flows = dict()
        self.res_flow = []

        self.dest = dest
        self.algorithm = algorithm

    # Finish generation
    def finish(self, flows=True):
        if flows:
            self.output()

        print("""
        Total Packets: [%i]
        Exported Flows: [%i]
        Open Flows: [%i]
                    """%(self.packets, len(self.res_flow), len(self.open_flows)))

    # Output a line
    def output(self):
        if self.dest:
            f = open(self.dest, 'w')

        for flow in self.res_flow:
            if self.dest:
                f.write(flow.output())
            else:
                print flow.output()
        for key, flow in self.open_flows.iteritems():
            if self.dest:
                f.write(flow.output())
            else:
                print flow.output()

        if self.dest:
            f.close()

    # Add a record
    def add_record(self, rec):
        time = rec['start_time']
        length = rec['length']
        identifier = rec.identifier()

        # check time out
        remove_flows = []
        for key, flow in self.open_flows.iteritems():
            if flow.is_timeout(time, self.timeout):
                flow.update(time)
                self.complete += 1
                if self.algorithm:
                    print self.algorithm.predict(flow.get_sample())
                else:
                    self.res_flow.append(flow)
                remove_flows.append(key)

        for key in remove_flows:
            self.open -= 1
            del self.open_flows[key]

        stored_rec = self.open_flows.get(identifier, None)
        if stored_rec is not None: # if already exists
            stored_rec.update(time, length)
        else: # does not exist
            self.open += 1
            self.open_flows[identifier] = SharkFlow(rec)

        self.packets += 1

# The basic sniffer class
class Sniffer:

    def __init__(self, timeout=10.):
        # Scapy variables
        self.filter = "ip"
        self.store = 0
        self.iface = "en0"

        self.flow = NetflowGenerator(timeout)
        self.file = None

    # Convert to txt records
    def convert_txt(self, file_name, dest=None):
        self.convert(file_name, self.pkt_tshark_txt, dest)

    # Convert to flow records
    def convert_flow(self, file_name, dest=None):
        self.flow.start(dest)
        self.convert(file_name, self.pkt_tshark_flow, None)
        self.flow.finish()

    # Convert a filename to an action
    def convert(self, file_name, action, dest=None):
        print "Converting file: \"" + file_name + "\"."
        try:
            if dest:
                self.file = open(dest, "w")

            cmd = """tshark -o column.format:'"No.", "%%m", "Time", "%%t", "Source", "%%s", "Destination", "%%d", "Protocol", "%%p", "len", "%%L", "srcport", "%%uS", "dstport", "%%uD"' -r %s""" % file_name
            self.tshark(cmd, action, split=False)

            if dest:
                self.file.close()
                self.file = None
        except (IOError, OSError):
            print "Could not open file: \"" + file_name + "\"."
        else:
            print "Done converting file: \"" + file_name + "\"."

    def sniff_tshark(self, algorithm):
        try:
            self.flow.start(algorithm=algorithm)
            cmd = """tshark -o column.format:'"No.", "%m", "Time", "%t", "Source", "%s", "Destination", "%d", "Protocol", "%p", "len", "%L", "srcport", "%uS", "dstport", "%uD"' """
            self.tshark(cmd, self.pkt_tshark_flow, split=False)
        except OSError:
            print "Error sniffing packets."
        except KeyboardInterrupt:
            self.flow.finish(False)
            print "Quitted packet sniffer..."

    # Start scapy
    def start(self, cmd):
        try:
            self.scapy(self.pkt_callback, self.iface, self.filter, self.store)
        except KeyboardInterrupt as e:
            pass

    # Run tshark for packet sniffing
    def tshark(self, command, action, split=True):
        cmd = command
        if split:
            cmd = command.split()
        for l in self.runProcess(cmd, shell = not split):
            action(l)

    # Use scapy for packet sniffing
    def scapy(self, action, iface, filter, store):
        from scapy.all import sniff
        sniff(iface=iface, prn=action, filter=filter, store=store)

    # Run a process and capture the output
    def runProcess(self, exe, shell=False):
        import subprocess
        p = subprocess.Popen(exe, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=shell)
        return iter(p.stdout.readline, b'')

    # Callback for scapy
    def pkt_callback(self, pkt):
    	pkt.show() # debug statement

    # Keep current line
    def pkt_tshark_txt(self, pkt):
        if not (pkt[:1].isdigit() or pkt[:1] == " "):
            return
        if self.file:
            self.file.write(pkt)
        else:
            print pkt,

    # Convert one line from tshark into a flow line
    def pkt_tshark_flow(self, pkt):
        if not (pkt[:1].isdigit() or pkt[:1] == " "):
            return
        f = SharkPacket(pkt)
        self.flow.add_record(f)
