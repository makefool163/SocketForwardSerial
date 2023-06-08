# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

# 串口数据流中 FF 每个数据包的标头特殊指示字符
# 1. FF FF = FF 实际字符，本数据包内容就是 FF
# 2. FF FE XX YY  
#    XX是约定的新连接序号
#   2.1 YY = 00 新连接发起, 
#    服务器端，连接成功后，则不回复，进入正常数据发送
#    新连接来的时候，XX要分配一个00~FD之间的序号，如果没有可分配的，就拒绝连接
#   2.2 YY = 01 若服务器端连接失败，则返回 FF FE XX 01
#   2.3 YY = 02 若网络连接（无论哪S/T端）断开，向对端发送 FF FE XX 02，通知对端相应的连接
# 3. FF XX (XX 不等于 FF 或 FE) 譬如 FF 00, FF 01, FF 02 ... 
#    XX是约定的新连接序号，后面就是实际的数据包内容，
#    直到遇到FF（标头特殊指示字符），说明碰到一个新数据包了

import eventlet
import serial
import queue
import struct
import argparse
from eventlet import tpool, backdoor
import socket

class SerialSocket(serial.Serial):
    def recv(self):
        # 等待
        data = tpool.execute(self.read, 1)
        # 读完
        while self.in_waiting:
            data += tpool.execute(self.read, self.in_waiting)
        return data

def com_listen_message():
    ss = SerialSocket("com10")
    buffer = b''
    while True:
        g = eventlet.spawn(ss.recv)
        data = g.wait()
        buffer +=data

class Socket2Ser_Base:
    def __init__(self, ip, port, com_port, baud_rate, debug=False):
        self.debug = debug
        self.ip = ip
        self.port = port
        self.com_port = com_port
        self.com = SerialSocket(port=com_port, timeout=None, baudrate=baud_rate)
        # baud_rate = 115200
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
            try:
                d = sock.recv(32384)
            except Exception as e:
                # 对付可能的接收错误，特别是sock失效了
                # 当然可能是被主协程给关掉了
                if self.debug:
                    print (e)
                    # 测试结果的确是，在服务器端，主协程会关这个
                break
            # 重新组合数据，处理FF
            if len(d) > 0:
                # eventlet的sock.recv是阻塞模式
                # 1. 有实际数据来，阻塞会打开，返回实际数据
                # 2. 对端断开连接，阻塞也会打开，返回空数据
                d = d.replace(b"\xff",b"\xff\xff")
                d = b"\xff" + struct.pack("!B", socket_id) + d
                self.com_send_Queue.put(d)
            else:
                # 对端已断开连接
                # 要把这个中断信号传递到对端去... 
                # 如果是T端还好，告诉S端关闭对应的连接即可
                # 若是S端中断，说明S端的服务关掉了，啥都没有了
                # 总归老连接关闭，以后的新连接拒绝服务连接，直到S端的服务恢复
                print ("net_recv closed.")
                if socket_id in self.socket_stock:
                    # 字典pop不会被协程切走，先干为快
                    self.socket_stock.pop(socket_id)
                    # 下面的三行，应该有很严密的时间先后关系
                    # 因为在协程体系下，使可能被其他协程切换出去的
                    sock.close()
                    self.com_send_Queue.put(b"\xff\xfe" + struct.pack("!B", socket_id) + b"\x02")
                    self.socket_pool.put(socket_id)
                    # 通告对端，网络连接已经断了
                break
    def net_send(self):
        while True:
            id, buf = self.net_send_Queue.get(True)
            if id in self.socket_stock:
                sock = self.socket_stock[id]
                sock.send(buf)
    def print_hex(self, buf, f):
        # 把输入的 bytes 打印成 16进制形式
        hex = ''
        for b in buf:
            hex += f + format(b, '02x')
        print (hex, end="", flush=True)
    def com_send(self):
        while True:
            buf = self.com_send_Queue.get(True)
            self.com.write(buf)
            if self.debug:
                self.print_hex(buf, "-")
    def com_recv(self):
        while True:
            try:
                g = self.pool.spawn(self.com.recv)
                d = g.wait() # 协程读取com口
                if self.debug:
                    self.print_hex(d, "_")
                b = b""
                while len(d) > 0:
                    d0 = d[0:1]
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
            except (SystemExit, KeyboardInterrupt):
                break
    def com_leading_packet_proc(self):
        if len(self.com_leading_packet_buf) >= 2 \
            and self.com_leading_packet_buf[:2] == b"\xff\xff":
            self.net_send_Queue.put((self.com_sock_id_online, b"\xff"))
            self.com_leading_packet_buf = b""
            self.com_in_status = False
        else:
            if len(self.com_leading_packet_buf) >= 2 \
                and self.com_leading_packet_buf[:2] != b"\xff\xfe":
                self.com_sock_id_online = self.com_leading_packet_buf[1]
                self.com_leading_packet_buf = b""
                self.com_in_status = False
        
class Socket2Ser_Client(Socket2Ser_Base):
    def socket_on_close(self):
        pass
    def Start(self):
        print ("self.ip", self.ip)
        server_sock = eventlet.listen((self.ip, self.port), reuse_addr = True, backlog=0xfe)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # 启动alive探测
        server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 20)
        # 空闲时间    
        server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
        # 探测间隔
        server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        # 探测次数
        # 这样对端连接断开后，最少 29秒后，本端也会断开
        self.pool.spawn_n(self.com_recv)
        self.pool.spawn_n(self.com_send)        
        #pool.spawn_n(self.net_recv)
        # listen 的recv 只有被 accept 后，才会有
        self.pool.spawn_n(self.net_send)
        while True:
            try:
                print ("Start Listening accept wait...")
                new_sock, address = server_sock.accept()
                print("accepted", address, end=" ")
                try:
                    socket_id = self.socket_pool.get()
                    self.socket_stock[socket_id] = new_sock
                    out_str = b"\xff\xfe" + struct.pack("!B", socket_id) + b"\x00"
                    self.com_send_Queue.put(out_str)
                    self.pool.spawn_n(self.net_recv, new_sock, socket_id)                
                    # 启动网络 收报 协程
                    print ("accept success at: ", socket_id)
                except queue.Empty:
                    # 连接池已经空了，不能连接了
                    new_sock.close()
                    print ("accept fail.")
            except (SystemExit, KeyboardInterrupt):
                break
    def com_leading_packet_proc(self):
        if len(self.com_leading_packet_buf) >=4 \
            and self.com_leading_packet_buf[1] == b"\xFE" \
            and self.com_leading_packet_buf[3] == b"\x01":
                # 运行在客户模式下：
                # 服务器返回连接失败的处理
                id = struct.unpack("!B", self.com_Forward_buf[1])
                sock = self.socket_stock[id]
                # 不管 close 是否 成功, 先必须把前导符号消除，因为 close 的动作会进入协程切换状态
                self.com_leading_packet_buf = b""
                self.com_in_status = False
                sock.close()
                # 此处可以不回收 id，断开后，在net_recv中会有处理
                # self.socket_pool.put(id)
        super().com_leading_packet_proc()

class Socket2Ser_Server(Socket2Ser_Base):
    def Start(self):
        #pool.spawn_n(self.com_recv)
        self.pool.spawn_n(self.com_send)        
        # pool.spawn_n(self.net_recv)
        # 只有从com发了连接信号后，才会去连接服务器，产生recv过程
        self.pool.spawn_n(self.net_send)
        self.com_recv() # 进入读取 com 口的循环
    def com_leading_packet_proc(self):
        #print ("buf:",self.com_leading_packet_buf)
        if len(self.com_leading_packet_buf) >=4:
            if self.com_leading_packet_buf[:2] == b"\xff\xfe" \
            and self.com_leading_packet_buf[3] == 0x00:
                # 运行在服务器模式下：
                # 收到客户端的连接请求的处理
                print ("try fork ...", self.ip, self.port, end=" ")
                id = self.com_leading_packet_buf[2]
                # 不管 connect 是否 成功, 先必须把前导符号消除，因为 connect 的动作会进入协程切换状态
                self.com_leading_packet_buf = b""
                self.com_in_status = False
                try:
                    sock = eventlet.connect((self.ip, self.port))
                    print ("fork a connect", end=" ")
                    self.socket_stock[id] = sock
                    print("accepted", id)
                    self.pool.spawn_n(self.net_recv, sock, id)
                    # 启动网络 收报 协程
                except:
                    # 连接服务失败
                    out_str = b"\xff\xfe" + struct.pack("!B", id) + b"\x01"
                    self.com_send_Queue.put(out_str)
            if self.com_leading_packet_buf[:2] == b"\xff\xfe" \
            and self.com_leading_packet_buf[3] == 0x02:
                # 运行在服务器模式下：
                # 收到客户端的连接已中断关闭
                socket_id = self.com_leading_packet_buf[2]
                print ("close connect ", socket_id)
                # 不管 是否 成功, 先必须把前导符号消除，避免后面进入协程切换状态
                self.com_leading_packet_buf = b""
                self.com_in_status = False
                if socket_id in self.socket_stock:
                    sock = self.socket_stock[socket_id]
                    # 字典pop不会被协程切走，先干为快
                    self.socket_stock.pop(socket_id)
                    # 下面的应该有很严密的时间先后关系
                    # 因为在协程体系下，使可能被其他协程切换出去的
                    sock.close()
                    #self.com_send_Queue.put(b"\xff\xfe" + struct.pack("!B", socket_id) + b"\x02")
                    # 无需发到对端，因为是对端通告来的关闭信号
                    self.socket_pool.put(socket_id)

        super().com_leading_packet_proc()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Forward socket service to another computer via a serial port.")
    parser.add_argument('Action', choices=['S', 'T'], type=str, help='act as forwarding Source or Target')
    parser.add_argument('-ip', default='localhost', type=str, help="Connect to Server IP when act as Source, default is localhost")
    parser.add_argument('-port', default=22, type=int, nargs=1, required=True, help='Connect to Server port when act as source/Listen port when act as target, default is 22')
    parser.add_argument('-com', type=str, nargs=1, required=True, help="Serial Port")
    parser.add_argument('-baudrate', type=int, default=115200, help="Serial Port baudrate")
    parser.add_argument('-d', "--debug", action="store_true", help="set debug out")
    parser.add_argument('-b', "--backdoor", action="store_true", help="set backdoor debug")
    args = parser.parse_args()
    #print (args.port)

    if args.backdoor:
        eventlet.spawn(backdoor.backdoor_server, eventlet.listen(('localhost', 55555)), locals())
    if args.Action == "S":
        ss = Socket2Ser_Server(args.ip, args.port[0], args.com[0], args.baudrate, args.debug)
    else:
        ss = Socket2Ser_Client(args.ip, args.port[0], args.com[0], args.baudrate, args.debug)
    ss.Start()
