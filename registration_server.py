import socket
import time
import struct
import threading
import timeit
from threading import Timer
import sys
import random
import os

# (ip, port) - > name
address_to_name = {}

# (name, ip, port) - > (data, timer, src)
registered = {}

# (ip, port) -> (seq_num, timer)
probes = {}

lock = threading.RLock()

def timeout(ip, port):
    # print address_to_name
    name = address_to_name[(ip, port)]
    lock.acquire()
    try:
        del address_to_name[(ip, port)]
        del registered[(name, ip, port)]
    finally:
        lock.release()
    print "timeout %s : %d" % (ip, port)

def probe(ip, port, sock):
    print "probe"
    timer = Timer(5.0, timeout, [ip, port])
    timer.start()
    sequence_number = session_id = random.randint(0, 0xff)
    lock.acquire()
    try:
        name = address_to_name[(ip, port)]
        key = (name, ip, port)
        registration_agent = registered[key][2]
    finally:
        lock.release()
    probes[(ip, registration_agent)] = (sequence_number, timer)
    magic =  50273.0
    message = struct.pack('>HBB', magic, sequence_number, 6)    
    sock.sendto(message, (ip, registration_agent))

def ACK(sequence_number, socket, address):
    print "ack"
    magic =  50273.0
    message = struct.pack('>HBB', magic, sequence_number, 7)    
    socket.sendto(message, address)

def unregister(sequence_number, data, sock, address):
    print "unregister"
    unpacked = struct.unpack('>4sH', data)
    ip = socket.inet_ntoa(unpacked[0])
    port = unpacked[1]
    lock.acquire()
    try:
        if (ip, port) in address_to_name:
            name = address_to_name[(ip, port)]
            key = (name, ip, port)
            registered[key][1].cancel()
            del address_to_name[(ip, port)]
            del registered[key]
    finally:
        lock.release()
    ACK(sequence_number, sock, address)

def fetch(sequence_number, data, sock, address):
    print "fetch"
    length = len(data) - 1
    unpacked = struct.unpack('>B%ds' % length, data)
    name = unpacked[1]
    # 0xC461,  seqnum, 0x03,  len , service name
    entries = []
    lock.acquire()
    try:
        for key in registered:
            if len(entries) > 100:
                break
            if name == '' or name in key[0]:
                ip = ip2int(key[1])
                port = key[2]
                data = registered[key][0]
                entries.append(struct.pack('>IH4s', ip, port, data))
    finally:
        lock.release()
    magic =  50273.0
    string_format = ''
    for i in range(len(entries)):
        string_format += '10s'
    message = struct.pack('>HBBB%s' % string_format, magic, sequence_number, 4, len(entries), *entries)    
    sock.sendto(message, address)

def register(sequence_number, data, sock, address):
    print "register"
    length = len(data) - 11
    unpacked = struct.unpack('>4sH4sB%ds' % length, data)
    ip = socket.inet_ntoa(unpacked[0])
    port = unpacked[1]
    data = unpacked[2]
    name = unpacked[4]
    lock.acquire()
    key = (name, ip, port)
    # print key
    try:
        if (ip, port) in address_to_name and address_to_name[(ip, port)] != name:
            old_name = address_to_name[(ip, port)]
            registered[(old_name, ip, port)][1].cancel()
            timer = Timer(240.0, timeout, [ip, port])
            timer.start()
            del registered[(old_name, ip, port)]
            del address_to_name[(ip, port)]
            registered[key] = (data, timer, int(address[1]) + 1)
            address_to_name[(ip, port)] = name
        elif key in registered:
            registered[key][1].cancel()
            timer = Timer(240.0, timeout, [ip, port])
            timer.start()
            registered[key] = (data, timer, int(address[1]) + 1)
        else:
            address_to_name[(ip, port)] = name
            timer = Timer(240.0, timeout, [ip, port])
            timer.start()
            registered[key] = (data, timer, int(address[1]) + 1)
    finally:
        lock.release()
    magic =  50273.0
    message = struct.pack('>HBBH', magic, sequence_number, 2, 5)    
    sock.sendto(message, address)

def process(data, address, socket):
    length = len(data) - 12
    header = data[:4]
    unpacked = struct.unpack('>HBB', header)
    # magic number, sequence_number, command
    sequence_number = unpacked[1]
    command = unpacked[2]
    if command == 1:
        #go register
        register(sequence_number, data[4:], socket, address)
        # print registered
        # probe(address[0], address[1], socket)
        # print "send probe to %s : %d" % address
    elif command == 3:
        #go fetch
        fetch(sequence_number, data[4:], socket, address)
    elif command == 5:
        #go unregister
        unregister(sequence_number, data[4:], socket, address)
    elif command == 6:
        #received probe
        print "recieved probe from ip: %s port: %d" % (address[0], address[1])
        ACK(sequence_number, socket, address) 
    elif command == 7:
        # received ACK
        print "received ACLLL"
        if address in probes and probes[address][0] == sequence_number:
            probes[address][1].cancel()
            del probes[address]
    

def main(hostname, port):
    if hostname == 'localhost':
        host = "0.0.0.0"
    else:
        host = socket.gethostbyname(hostname)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host, port))   
    print "Listening on port %s" % port
    while True:
        try:
            while 1:
                data, addr = s.recvfrom(1024)
                if not data:    
                    # Close connection and wait for new connections
                    print "Other side disconnected! Closing connection."
                    break
                else:
                    if threading.active_count() < 8:
                        t = threading.Thread(target=process, args=(data, addr, s,))
                        t.start()

        except KeyboardInterrupt:
            print
            print "Interrupted! Closing connection and socket."
            try:
                conn.close()
            except NameError:
                "(No connection open.)"
            s.close()
            os._exit(1)
            break
        except socket.error, msg:
            print "Socket error! %s" % msg
            break
        except Exception as e:
            print e 

def ip2int(addr):  
    num = struct.unpack("!I", socket.inet_aton(addr))[0]
    return num

 
if __name__ == "__main__":
    if len(sys.argv) > 2:
        print "running on %s" % sys.argv[1]
        main(sys.argv[1], int(sys.argv[2]))
    else:
        print "running on locahost"
        main("localhost", 33433)