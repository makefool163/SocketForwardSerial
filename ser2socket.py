# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

# 串口数据流中 FF 作为特殊应用引用字符
# 1. FF FF = FF 实际字符
# 2. FF FE XX 00 新连接发起, XX是约定的新连接序号
#    服务器端，连接成功后，则不回复，进入正常数据发送
#    若服务器端连接失败，则返回 FF FE XX 01
# 3. FF 00, FF 01, FF 02 ... 作为connect数据包指示导引字符 00, 01, 02的指示对应的连接序号
#    新连接来的时候，要分配一个00~FD之间的序号，如果没有可分配的，就拒绝连接
# 4. 需要知道每个数据包的长度吗？（似乎无必要）

import eventlet
import serial
import queue
import struct
import argparse

class SerialSocket(serial.Serial):
    def recv(self):
        # 等待
        data = eventlet.tpool.execute(self.read, 1)
        # 读完
        while self.in_waiting:
            data += eventlet.tpool.execute(self.read, self.in_waiting)
        return data

def com_listen_message():
    ss = SerialSocket("com10")
    buffer = b''
    while True:
        g = eventlet.spawn(ss.recv)
        data = g.wait()
        buffer +=data

class Ser2socket_Base:
    def __init__(self, ip, port, com_port, baud_rate, debug=False):
        self.debug = debug
        self.ip = ip
        self.port = port
        self.com_port = com_port
        self.com = SerialSocket(com_port, baud_rate) # baud_rate = 115200
        self.com_read_interface = eventlet.spawn(self.com.recv)
        self.socket_pool = eventlet.queue.Queue() # socket连接序号的pool
        for i in range(0xFE):
            self.socket_pool.put(i)
        self.com_send_Queue = eventlet.queue.Queue() # com口等待发送queue
        self.com_recv_Queue = eventlet.queue.Queue() # com口输入queue，用以处理FF前导符
        self.net_send_Queue = eventlet.queue.Queue()
        self.socket_stock = {}
        self.com_in_status = True # False 正常传送状态, True 前导处理状态
        self.com_leading_packet_buf = b""
        self.com_sock_id_online = 0 
        self.pool = eventlet.GreenPool()
    def net_recv(self, sock, socket_id):
        while True:
            d = sock.recv(32384)
            if d == '':
                # net 输入断开
                self.socket_pool.put(socket_id)
                break
            # 重新组合数据，处理FF
            d = d.replace(b"\xff",b"\xff")
            d = b"\xff" + struct.pack("!B", socket_id) + d
            self.com_out_Queue.put(d)
    def net_send(self):
        while True:
            id, buf = self.net_send_Queue.get(True)
            sock = self.socket_stock[id]
            sock.send(buf)
    def com_send(self, fd):
        def print_hex(d):
            # 把输入的 bytes 打印成 16进制形式
            hex = ''
            for dd in d:
                hex += format(dd, '02x') + " "
            print (hex, end=" ", flush=True)
        while True:
            buf = self.com_send_Queue.get(True)
            self.com.write(buf)
            if self.debug:
                print_hex(d)
    def com_recv(self):
        while True:
            try:
                d = self.com_read_interface.wait() # 协程读取com口
                b = b""
                while len(d) > 0:
                    d0 = d
                    d = d[1:]
                    if self.com_in_status:
                        # 前导处理状态
                        self.com_leading_packet_buf += d0
                        self.com_leading_packet_proc()
                    else:
                        if d0 == b"\xff":
                            if len(b) > 0:
                                self.net_send_Queue.put((self.com_sock_id_online, b))
                                b = b""
                            self.com_leading_packet_buf = b"\xff"
                            self.com_in_status = True
                        else:
                            b += d0
                if len(b) > 0:
                    self.net_send_Queue.put((self.com_sock_id_online, b))
                    b = b""
            except (SystemExit, KeyboardInterrupt):
                break
    def com_leading_packet_proc(self):
        if self.com_leading_packet_buf[1] == b"\xFF":
            self.net_send_Queue.put(self.com_sock_id_online, b"\xFF")
            self.com_in_status = False
        else:
            if len(self.com_leading_packet_buf) == 2:
                self.com_sock_id_online = struct.unpack("!B", self.com_leading_packet_buf[1])
                self.com_in_status = False

class Ser2socket_Client(Ser2socket_Base):
    def Start(self):
        server = eventlet.listen((self.ip, self.port), reuse_addr = True, reuse_port=True)
        self.pool.spawn_n(self.com_recv)
        self.pool.spawn_n(self.com_send)        
        #pool.spawn_n(self.net_recv)
        # listen 的recv 只有被 accept 后，才会有
        self.pool.spawn_n(self.net_send)
        while True:
            try:
                new_sock, address = server.accept()
                try:
                    socket_id = self.socket_pool.get()
                except queue.Empty:
                    # 连接池已经空了，不能连接了
                    new_sock.close()
                self.socket_stock[socket_id] = new_sock
                self.com_out_Queue.put(b"\xff\xfe" + struct.pack("!B") + b"\x00")
                print("accepted", address)
                self.pool.spawn_n(self.net_recv, new_sock, socket_id)
                # 启动网络 收报 协程
            except (SystemExit, KeyboardInterrupt):
                break
    def com_leading_packet_proc(self):
        if self.com_leading_packet_buf[1] == b"\xFE":
            if len(self.com_leading_packet_buf) == 4:
                if self.com_leading_packet_buf[-1] == b"\x01":
                    # 运行在客户模式下：
                    # 服务器返回连接失败的处理
                    id = struct.unpack("!B", self.com_Forward_buf[1])
                    sock = self.socket_stock[id]
                    sock.close()
                    # 此处可以不回收 id，断开后，在net_recv中会有处理
                    # self.socket_pool.put(id)
                    self.com_in_status = False
        super().com_leading_packet_proc()

class Ser2socket_Server(Ser2socket_Base):
    def Start(self):
        #pool.spawn_n(self.com_recv)
        self.pool.spawn_n(self.com_send)        
        # pool.spawn_n(self.net_recv)
        # 只有从com发了连接信号后，才会去连接服务器，产生recv过程
        self.pool.spawn_n(self.net_send)
        self.com_recv() # 进入读取 com 口的循环
    def com_leading_packet_proc(self):
        if self.com_leading_packet_buf[1] == b"\xFE":
            if len(self.com_leading_packet_buf) == 4:
                if self.com_leading_packet_buf[-1] == b"\x00":
                    # 运行在服务器模式下：
                    # 收到客户端的连接请求的处理
                    id = struct.unpack("!B", self.com_leading_packet_buf[2])
                    try:
                        sock = eventlet.connect((self.ip, self.port))
                        self.socket_stock[id] = sock
                        print("accepted", id)
                        self.pool.spawn_n(self.com_recv, sock, id)
                        # 启动网络 收报 协程
                    except:
                        # 连接服务失败
                        out_str = b"\xff\xfe" + struct.pack("!B", id) + b"\x01"
                        self.com_out_Queue.put(out_str)
        super().com_leading_packet_proc()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Forward socket service to another computer via a serial port.")
    parser.add_argument('Action', choices=['S', 'T'], type=str, help='act as forwarding Source or Target')
    parser.add_argument('-ip', default='localhost', type=str, help="Connect to Server IP when act as Source, default is localhost.")
    parser.add_argument('-port', default=22, type=int, nargs=1, required=True, help='Connect to Server port when act as source/Listen port when act as target, default is 22')
    parser.add_argument('-com', type=str, nargs=1, required=True, help="Serial Port")
    parser.add_argument('-baudrate', type=int, default=9600, help="Serial Port baudrate")
    parser.add_argument('-d', "--debug", action="store_true", help="set debug out")
    args = parser.parse_args()

    if args.Action == "S":
        ss = Ser2socket_Server(args.ip, args.port, args.com, args.baudrate, args.debug)
    else:
        ss = Ser2socket_Client(args.ip, args.port, args.com, args.baudrate, args.debug)
    ss.Start()
